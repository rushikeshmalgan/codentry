"""The single DB-polling worker: durability across restarts, crash recovery,
delivery sweeping, and never dying on an error."""

import threading
import time
from datetime import timedelta

from app import worker as worker_module
from app.worker import ReviewWorker
from tests.github_payloads import pull_request_payload
from tests.job_helpers import configured_settings, enqueue, now


def _worker(store, **overrides):
    return ReviewWorker(store, configured_settings(worker_poll_seconds=0.02, **overrides))


def test_poll_with_no_work_returns_false_and_does_nothing(store):
    assert _worker(store).run_once() is False


def test_poll_claims_and_executes_a_due_job(store, monkeypatch):
    run, _ = enqueue(store)
    seen = []
    monkeypatch.setattr(
        worker_module, "execute_review_run", lambda st, job, settings: seen.append(job)
    )

    assert _worker(store).run_once() is True

    assert [j["id"] for j in seen] == [run["id"]]
    assert seen[0]["status"] == "running" and seen[0]["attempts"] == 1


def test_a_job_survives_a_worker_restart_because_it_is_a_row_not_a_task(store, monkeypatch):
    """Worker 1 claims the job and 'dies' (never finishes). A brand-new
    worker instance — the process restarted — picks it up once the lease expires."""
    run, _ = enqueue(store)
    first = store.claim_next_review_run(600, now=now())  # worker 1 starts the job...
    assert first["attempts"] == 1
    # ...and the process dies. Time passes; its lease is now in the past.
    store.update_review_run(run["id"], available_at=(now() - timedelta(seconds=5)).isoformat())

    seen = []
    monkeypatch.setattr(
        worker_module, "execute_review_run", lambda st, job, settings: seen.append(job)
    )
    fresh_worker = _worker(store)  # new instance, no shared memory with the "crashed" one

    assert fresh_worker.run_once() is True
    assert seen[0]["id"] == run["id"] and seen[0]["attempts"] == 2


def test_poll_never_raises_even_if_the_store_or_runner_explodes(store, monkeypatch):
    enqueue(store)

    def boom(*a, **k):
        raise RuntimeError("runner exploded")

    monkeypatch.setattr(worker_module, "execute_review_run", boom)
    assert _worker(store).run_once() is False  # logged, swallowed

    monkeypatch.setattr(store, "claim_next_review_run", boom)
    assert _worker(store).run_once() is False


def test_first_poll_sweeps_stuck_deliveries_from_their_stored_payload(store, monkeypatch):
    payload = pull_request_payload(head_sha="swept")
    store.claim_delivery("stuck-1", "pull_request", payload)
    store.mark_delivery("stuck-1", "retryable", "boom")
    monkeypatch.setattr(worker_module, "execute_review_run", lambda *a, **k: None)

    _worker(store).run_once()

    assert store.get_delivery("stuck-1")["status"] == "succeeded"


def test_thread_processes_jobs_and_stops_cleanly(store, monkeypatch):
    run, _ = enqueue(store)
    done = threading.Event()

    def fake_execute(st, job, settings):
        st.finalize_review_run(
            job["id"], job["attempts"], status="completed", findings=[], analysis_meta=None,
            error_code=None, error_message=None, latency_ms=1,
        )
        done.set()

    monkeypatch.setattr(worker_module, "execute_review_run", fake_execute)
    worker = _worker(store)
    assert worker.running is False

    worker.start()
    try:
        assert done.wait(5), "worker thread never picked up the job"
        assert worker.running is True
    finally:
        worker.stop(timeout=5)

    assert worker.running is False
    assert store.get_review_run(run["id"])["status"] == "completed"


def test_worker_thread_is_a_daemon_and_start_is_idempotent(store):
    worker = _worker(store)
    worker.start()
    try:
        first_thread = worker._thread
        worker.start()
        assert worker._thread is first_thread
        assert first_thread.daemon is True
    finally:
        worker.stop(timeout=5)


def test_worker_keeps_polling_after_a_failed_iteration(store, monkeypatch):
    enqueue(store, pr_number=1, head_sha="a")
    enqueue(store, pr_number=2, head_sha="b", delivery_id="d2")
    calls = []

    def flaky_execute(st, job, settings):
        calls.append(job["id"])
        if len(calls) == 1:
            raise RuntimeError("first job explodes")

    monkeypatch.setattr(worker_module, "execute_review_run", flaky_execute)
    worker = _worker(store)
    worker.start()
    try:
        deadline = time.monotonic() + 5
        while len(calls) < 2 and time.monotonic() < deadline:
            time.sleep(0.02)
    finally:
        worker.stop(timeout=5)

    assert len(calls) == 2  # the second job still ran

"""The two durable state machines, against the store contract.

These run against InMemoryReviewStore. SupabaseReviewStore implements the same
contract with conditional updates, but has NOT been run against a live
Postgres here — see docs/architecture.md "Not verified".
"""

import threading
from datetime import timedelta

import pytest

from analysis.finding import Finding
from app.events import EventPayloadError, handle_pull_request_event
from app.ingest import process_event, sweep_deliveries
from app.store import DELIVERY_LEASE_SECONDS, MAX_DELIVERY_ATTEMPTS, InMemoryReviewStore
from tests.github_payloads import pull_request_payload
from tests.job_helpers import claim, enqueue, now

PAYLOAD = {"any": "payload"}


# =========================== webhook_deliveries ===============================


def test_new_delivery_is_recorded_as_processing_with_its_payload(store):
    claim_ = store.claim_delivery("d1", "pull_request", PAYLOAD)
    row = store.get_delivery("d1")
    assert claim_.state == "new" and claim_.attempts == 1
    assert row["status"] == "processing" and row["payload"] == PAYLOAD


def test_only_a_succeeded_delivery_is_a_duplicate(store):
    store.claim_delivery("d1", "pull_request", PAYLOAD)
    store.mark_delivery("d1", "succeeded")
    assert store.claim_delivery("d1", "pull_request", PAYLOAD).state == "duplicate"


def test_delivery_that_failed_is_reclaimed_on_redelivery_not_swallowed(store):
    """The Phase 3 bug: recorded-before-processing turned every retry into a duplicate."""
    store.claim_delivery("d1", "pull_request", PAYLOAD)
    store.mark_delivery("d1", "retryable", "ConnectionError")

    again = store.claim_delivery("d1", "pull_request", PAYLOAD)

    assert again.state == "reclaimed" and again.attempts == 2
    assert store.get_delivery("d1")["status"] == "processing"


def test_permanently_failed_delivery_can_still_be_redelivered_by_hand(store):
    store.claim_delivery("d1", "pull_request", PAYLOAD)
    store.mark_delivery("d1", "failed", "bad payload")
    assert store.claim_delivery("d1", "pull_request", PAYLOAD).state == "reclaimed"


def test_a_fresh_processing_delivery_is_in_progress_not_reprocessed(store):
    store.claim_delivery("d1", "pull_request", PAYLOAD)
    assert store.claim_delivery("d1", "pull_request", PAYLOAD).state == "in_progress"


def test_a_stale_processing_delivery_is_reclaimed_after_the_lease(store):
    t0 = now()
    store.claim_delivery("d1", "pull_request", PAYLOAD, now=t0)
    later = t0 + timedelta(seconds=DELIVERY_LEASE_SECONDS + 1)
    again = store.claim_delivery("d1", "pull_request", PAYLOAD, now=later)
    assert again.state == "reclaimed" and again.attempts == 2


def test_concurrent_claims_of_one_delivery_produce_exactly_one_owner():
    store = InMemoryReviewStore()
    results = []
    barrier = threading.Barrier(8)

    def worker():
        barrier.wait()
        results.append(store.claim_delivery("race", "pull_request", PAYLOAD).state)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    [t.start() for t in threads]
    [t.join() for t in threads]

    assert results.count("new") == 1
    assert results.count("in_progress") == 7


def test_process_event_is_idempotent_for_a_reclaimed_event(store):
    payload = pull_request_payload(head_sha="h1")
    first = process_event(store, "pull_request", payload, "d1")
    second = process_event(store, "pull_request", payload, "d1")  # reprocessing
    assert first.review_run_id == second.review_run_id
    pr_id = store.get_review_run(first.review_run_id)["pull_request_id"]
    assert len(store.list_review_runs_for_pull_request(pr_id)) == 1


def test_sweeper_reprocesses_a_retryable_delivery_from_its_stored_payload(store):
    payload = pull_request_payload(head_sha="h1")
    store.claim_delivery("d1", "pull_request", payload)
    store.mark_delivery("d1", "retryable", "boom")  # e.g. DB blip after claiming

    counts = sweep_deliveries(store)

    assert counts["reprocessed"] == 1
    assert store.get_delivery("d1")["status"] == "succeeded"
    pr = store.get_repository_by_github_id(222)
    assert pr is not None and claim(store) is not None  # a job now exists


def test_sweeper_recovers_a_delivery_whose_handler_crashed_mid_flight(store):
    payload = pull_request_payload(head_sha="h1")
    t0 = now() - timedelta(seconds=DELIVERY_LEASE_SECONDS + 60)
    store.claim_delivery("d1", "pull_request", payload, now=t0)  # crashed: never marked

    counts = sweep_deliveries(store)

    assert counts["reprocessed"] == 1
    assert store.get_delivery("d1")["status"] == "succeeded"


def test_sweeper_leaves_a_healthy_in_flight_delivery_alone(store):
    store.claim_delivery("d1", "pull_request", pull_request_payload())
    assert sweep_deliveries(store) == {"reprocessed": 0, "failed_permanently": 0, "skipped": 0}
    assert store.get_delivery("d1")["status"] == "processing"


def test_sweeper_gives_up_after_max_attempts(store):
    payload = pull_request_payload()
    store.claim_delivery("d1", "pull_request", payload)
    store._deliveries["d1"]["attempts"] = MAX_DELIVERY_ATTEMPTS
    store.mark_delivery("d1", "retryable", "still broken")

    counts = sweep_deliveries(store)

    assert counts["failed_permanently"] == 1
    assert store.get_delivery("d1")["status"] == "failed"


def test_sweeper_marks_unprocessable_payloads_failed_not_retryable(store):
    store.claim_delivery("d1", "pull_request", {"action": "opened"})  # missing required fields
    store.mark_delivery("d1", "retryable", "x")
    counts = sweep_deliveries(store)
    assert counts["failed_permanently"] == 1
    assert store.get_delivery("d1")["status"] == "failed"


def test_payload_errors_are_permanent_by_type():
    with pytest.raises(EventPayloadError):
        process_event(InMemoryReviewStore(), "pull_request", {"action": "opened"}, "d")


# ============================ review_runs (jobs) ===============================


def test_enqueue_creates_a_pending_job_pinned_to_the_head_sha(store):
    run, result = enqueue(store, head_sha="h1", base_sha="b1")
    assert run["status"] == "pending" and run["head_sha"] == "h1" and run["base_sha"] == "b1"
    assert run["attempts"] == 0 and result["reason"] is None


def test_enqueue_is_idempotent_on_pull_request_and_head_sha(store):
    first, _ = enqueue(store, head_sha="h1", delivery_id="d1")
    second, result = enqueue(store, head_sha="h1", delivery_id="d2")  # redelivery / reopened
    assert first["id"] == second["id"]
    assert result["reason"] == "already_enqueued"
    assert len(store.list_review_runs_for_pull_request(first["pull_request_id"])) == 1


def test_a_new_head_supersedes_older_pending_jobs_deterministically(store):
    old, _ = enqueue(store, head_sha="h-old", updated_at="2026-01-01T10:00:00Z")
    new, _ = enqueue(store, head_sha="h-new", updated_at="2026-01-01T11:00:00Z", delivery_id="d2")

    assert store.get_review_run(old["id"])["status"] == "superseded"
    assert store.get_review_run(old["id"])["error_code"] == "superseded_by_newer_head"
    assert store.get_review_run(new["id"])["status"] == "pending"
    claimed = claim(store)
    assert claimed["id"] == new["id"]  # the only runnable job is the newest head


def test_running_job_is_not_touched_by_a_newer_enqueue(store):
    old, _ = enqueue(store, head_sha="h-old", updated_at="2026-01-01T10:00:00Z")
    claim(store)  # old is now running
    enqueue(store, head_sha="h-new", updated_at="2026-01-01T11:00:00Z", delivery_id="d2")
    assert store.get_review_run(old["id"])["status"] == "running"  # it notices at fetch/finalize


def test_stale_out_of_order_event_does_not_rewind_the_pull_request(store):
    enqueue(store, head_sha="h-new", updated_at="2026-01-01T11:00:00Z")
    run, result = enqueue(
        store, head_sha="h-old", updated_at="2026-01-01T10:00:00Z", delivery_id="d-late"
    )
    assert run is None and result["reason"] == "stale_event"
    pr = store.get_pull_request(result["pull_request_id"])
    assert pr["head_sha"] == "h-new"


def test_claim_makes_a_job_running_increments_attempts_and_sets_a_lease(store):
    run, _ = enqueue(store)
    t0 = now()
    claimed = store.claim_next_review_run(300, now=t0)
    assert claimed["id"] == run["id"] and claimed["status"] == "running"
    assert claimed["attempts"] == 1
    assert claim(store) is None  # a running job with a live lease is not claimable


def test_jobs_are_claimed_oldest_first(store):
    a, _ = enqueue(store, pr_number=1, head_sha="a")
    b, _ = enqueue(store, pr_number=2, head_sha="b", delivery_id="d2")
    assert claim(store)["id"] == a["id"]
    assert claim(store)["id"] == b["id"]


def test_crash_recovery_a_running_job_with_an_expired_lease_is_reclaimed(store):
    run, _ = enqueue(store)
    t0 = now()
    first = store.claim_next_review_run(60, now=t0)  # worker starts, then the process dies
    assert first["attempts"] == 1

    assert store.claim_next_review_run(60, now=t0 + timedelta(seconds=30)) is None  # lease alive
    second = store.claim_next_review_run(60, now=t0 + timedelta(seconds=61))

    assert second["id"] == run["id"] and second["attempts"] == 2


def test_a_job_that_keeps_crashing_fails_instead_of_looping_forever(store):
    run, _ = enqueue(store)
    t = now()
    for expected_attempt in (1, 2, 3):
        claimed = store.claim_next_review_run(60, now=t)
        assert claimed["attempts"] == expected_attempt
        t += timedelta(seconds=61)

    assert store.claim_next_review_run(60, now=t) is None
    stored = store.get_review_run(run["id"])
    assert stored["status"] == "failed" and stored["error_code"] == "max_attempts_exceeded"


def test_no_job_is_ever_left_running_forever_by_a_dead_worker(store):
    run, _ = enqueue(store)
    t0 = now()
    store.claim_next_review_run(60, now=t0)
    # Whatever happens next, after enough time the row leaves `running`.
    t = t0
    for _ in range(10):
        t += timedelta(seconds=61)
        store.claim_next_review_run(60, now=t)
    stored = store.get_review_run(run["id"])
    assert stored["status"] == "failed" and stored["attempts"] == 3  # bounded, and terminal


def test_concurrent_claims_give_a_job_to_exactly_one_worker():
    store = InMemoryReviewStore()
    handle_pull_request_event(store, pull_request_payload(head_sha="h1"))
    winners = []
    barrier = threading.Barrier(8)

    def worker():
        barrier.wait()
        job = store.claim_next_review_run(600)
        if job:
            winners.append(job["attempts"])

    threads = [threading.Thread(target=worker) for _ in range(8)]
    [t.start() for t in threads]
    [t.join() for t in threads]

    assert winners == [1]


def _finding(title="no-unused-vars", line=1, status="new"):
    return Finding(
        source="ESLINT", category="correctness", severity="high", title=title,
        description="d", file_path="a.js", start_line=line, end_line=line,
        dedup_hash=f"h-{title}-{line}", identity_key=f"k-{title}", change_status=status,
    )


def test_finalize_persists_findings_and_status_together_and_is_fenced(store):
    run, _ = enqueue(store)
    claimed = claim(store)

    ok = store.finalize_review_run(
        run["id"], claimed["attempts"], status="completed", findings=[_finding(), _finding(line=2)],
        analysis_meta={"k": 1}, error_code=None, error_message=None, latency_ms=12,
        merge_base_sha="mb",
    )

    stored = store.get_review_run(run["id"])
    assert ok and stored["status"] == "completed" and stored["merge_base_sha"] == "mb"
    assert stored["analysis_meta"] == {"k": 1} and stored["latency_ms"] == 12
    rows = store.get_findings_for_review_run(run["id"])
    assert len(rows) == 2 and {r["change_status"] for r in rows} == {"new"}
    assert rows[0]["identity_key"] == "k-no-unused-vars"


def test_finalize_with_a_stale_attempt_writes_nothing(store):
    run, _ = enqueue(store)
    t0 = now()
    stale = store.claim_next_review_run(60, now=t0)
    store.claim_next_review_run(60, now=t0 + timedelta(seconds=61))  # attempt 2 takes over

    ok = store.finalize_review_run(
        run["id"], stale["attempts"], status="completed", findings=[_finding()],
        analysis_meta=None, error_code=None, error_message=None, latency_ms=1,
    )

    assert ok is False
    assert store.get_findings_for_review_run(run["id"]) == []
    assert store.get_review_run(run["id"])["status"] == "running"


def test_finalize_replaces_findings_left_by_an_earlier_crashed_attempt(store):
    run, _ = enqueue(store)
    claimed = claim(store)
    store.create_findings(run["id"], [_finding("stale-from-crashed-attempt")])

    store.finalize_review_run(
        run["id"], claimed["attempts"], status="completed", findings=[_finding("fresh")],
        analysis_meta=None, error_code=None, error_message=None, latency_ms=1,
    )

    assert [r["title"] for r in store.get_findings_for_review_run(run["id"])] == ["fresh"]


def test_a_terminal_run_cannot_be_finalized_twice(store):
    run, _ = enqueue(store)
    claimed = claim(store)
    kwargs = dict(status="completed", findings=[], analysis_meta=None, error_code=None,
                  error_message=None, latency_ms=1)
    assert store.finalize_review_run(run["id"], claimed["attempts"], **kwargs) is True
    assert store.finalize_review_run(run["id"], claimed["attempts"], **kwargs) is False


def test_requeue_sets_backoff_and_preserves_the_attempt_count(store):
    run, _ = enqueue(store)
    claimed = claim(store)
    status = store.requeue_review_run(
        run["id"], claimed["attempts"], delay_seconds=120, error_code="server", error_message="502"
    )
    stored = store.get_review_run(run["id"])
    assert status == "pending" and stored["attempts"] == 1 and stored["error_code"] == "server"
    assert claim(store) is None  # not due for another 120s


def test_requeue_fails_the_run_once_attempts_are_exhausted(store):
    run, _ = enqueue(store)
    for _ in range(3):
        claimed = claim(store)
        status = store.requeue_review_run(
            run["id"], claimed["attempts"], delay_seconds=0, error_code="server", error_message="x"
        )
    assert status == "failed"
    assert store.get_review_run(run["id"])["status"] == "failed"


def test_only_failed_runs_can_be_manually_retried(store):
    run, _ = enqueue(store)
    assert store.retry_review_run(run["id"]) is None  # pending
    claimed = claim(store)
    assert store.retry_review_run(run["id"]) is None  # running
    store.finalize_review_run(
        run["id"], claimed["attempts"], status="failed", findings=[], analysis_meta=None,
        error_code="not_found", error_message="x", latency_ms=1,
    )
    retried = store.retry_review_run(run["id"])
    assert retried["status"] == "pending" and retried["attempts"] == 0
    assert retried["error_code"] is None
    assert claim(store)["attempts"] == 1


@pytest.mark.parametrize("terminal", ["completed", "partial"])
def test_completed_and_partial_runs_are_final(store, terminal):
    run, _ = enqueue(store)
    claimed = claim(store)
    store.finalize_review_run(
        run["id"], claimed["attempts"], status=terminal, findings=[], analysis_meta=None,
        error_code=None, error_message=None, latency_ms=1,
    )
    assert store.retry_review_run(run["id"]) is None
    assert store.supersede_review_run(run["id"], claimed["attempts"]) is False
    assert claim(store) is None


def test_supersede_is_fenced_and_only_applies_to_live_work(store):
    run, _ = enqueue(store)
    assert store.supersede_review_run(run["id"], None) is True  # pending
    assert store.get_review_run(run["id"])["status"] == "superseded"
    assert claim(store) is None


def test_job_context_joins_run_pull_request_repository_and_installation(store):
    run, _ = enqueue(store)
    ctx = store.get_job_context(run["id"])
    assert ctx.repository["full_name"] == "octo-team/widgets"
    assert ctx.installation["github_installation_id"] == 111
    assert ctx.pull_request["github_pr_number"] == 1
    assert store.get_job_context("no-such-run") is None

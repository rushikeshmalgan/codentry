"""Full-stack tests through TestClient: auth, durable dedup, event routing,
and job enqueueing.

The webhook no longer runs a review: it durably records the event, does
idempotent bookkeeping, and enqueues a `pending` job row. Execution is the
worker's job (tests/test_review_runner.py, tests/test_worker.py,
tests/test_e2e_local_mocked.py).
"""

import app.routes_internal as routes
from tests.github_payloads import (
    installation_payload,
    installation_repositories_payload,
    pull_request_payload,
)


def _post(client, headers, delivery_id, event_type, payload):
    return client.post(
        "/internal/webhook/pull-request",
        headers=headers,
        json={"delivery_id": delivery_id, "event_type": event_type, "payload": payload},
    )


# --- Authentication ---


def test_missing_internal_secret_is_rejected(client):
    resp = client.post(
        "/internal/webhook/pull-request",
        json={"delivery_id": "d1", "event_type": "pull_request", "payload": pull_request_payload()},
    )
    assert resp.status_code == 401


def test_invalid_internal_secret_is_rejected(client):
    resp = client.post(
        "/internal/webhook/pull-request",
        headers={"X-Codentry-Internal-Secret": "wrong-secret"},
        json={"delivery_id": "d1", "event_type": "pull_request", "payload": pull_request_payload()},
    )
    assert resp.status_code == 401


def test_valid_internal_secret_is_accepted(client, internal_headers):
    resp = _post(client, internal_headers, "d1", "pull_request", pull_request_payload())
    assert resp.status_code == 202


# --- Event routing ---


def test_pull_request_event_is_accepted_and_enqueues_a_pinned_pending_job(
    client, internal_headers, store
):
    resp = _post(
        client, internal_headers, "pr-1", "pull_request",
        pull_request_payload(action="opened", head_sha="headsha1", base_sha="basesha1"),
    )

    assert resp.status_code == 202
    body = resp.json()
    assert body["status"] == "accepted"
    review_run_id = body["review_run_id"]

    status_body = client.get(f"/internal/review-runs/{review_run_id}", headers=internal_headers).json()
    assert status_body["status"] == "pending"  # not run inline; the worker owns execution
    assert status_body["head_sha"] == "headsha1" and status_body["base_sha"] == "basesha1"
    assert status_body["attempts"] == 0 and status_body["started_at"] is None
    assert store.get_delivery("pr-1")["status"] == "succeeded"


def test_installation_event_accepted(client, internal_headers):
    resp = _post(
        client,
        internal_headers,
        "inst-1",
        "installation",
        installation_payload(action="created", repos=[{"id": 500, "full_name": "octo/x"}]),
    )
    assert resp.status_code == 202
    assert resp.json()["status"] == "accepted"


def test_installation_repositories_event_accepted(client, internal_headers):
    resp = _post(
        client,
        internal_headers,
        "instrepo-1",
        "installation_repositories",
        installation_repositories_payload(action="added", added=[{"id": 501, "full_name": "octo/y"}]),
    )
    assert resp.status_code == 202
    assert resp.json()["status"] == "accepted"


def test_unsupported_event_type_returns_422(client, internal_headers):
    resp = client.post(
        "/internal/webhook/pull-request",
        headers=internal_headers,
        json={"delivery_id": "d-bad", "event_type": "push", "payload": {}},
    )
    assert resp.status_code == 422


def test_malformed_pull_request_payload_returns_400(client, internal_headers):
    resp = _post(client, internal_headers, "d-malformed", "pull_request", {"action": "opened"})
    assert resp.status_code == 400


def test_unsupported_pull_request_action_is_ignored_not_errored(client, internal_headers):
    resp = _post(client, internal_headers, "d-labeled", "pull_request", pull_request_payload(action="labeled"))
    assert resp.status_code == 202
    body = resp.json()
    assert body["status"] == "ignored"
    assert body["reason"] == "unsupported_action"
    assert body["review_run_id"] is None


def test_inactive_repository_does_not_create_review_run(client, internal_headers, store):
    r1 = _post(
        client, internal_headers, "d-active", "pull_request",
        pull_request_payload(repo_id=777, action="opened"),
    )
    assert r1.json()["review_run_id"] is not None

    store.set_repository_active(777, is_active=False)

    r2 = _post(
        client, internal_headers, "d-inactive", "pull_request",
        pull_request_payload(repo_id=777, action="synchronize", pr_number=1),
    )
    body = r2.json()
    assert body["status"] == "ignored"
    assert body["reason"] == "repository_inactive"


# --- Replay protection ---


def test_duplicate_delivery_id_is_ignored(client, internal_headers):
    payload = pull_request_payload(repo_id=888, action="opened")

    r1 = _post(client, internal_headers, "dup-1", "pull_request", payload)
    r2 = _post(client, internal_headers, "dup-1", "pull_request", payload)

    assert r1.status_code == 202
    assert r1.json()["status"] == "accepted"
    assert r1.json()["review_run_id"] is not None

    assert r2.status_code == 202
    assert r2.json()["status"] == "duplicate_ignored"
    assert r2.json()["review_run_id"] is None


def test_first_delivery_of_a_new_id_is_always_accepted(client, internal_headers):
    resp = _post(client, internal_headers, "fresh-id-123", "pull_request", pull_request_payload())
    assert resp.json()["status"] == "accepted"


# --- Reliability: an event is never lost because a previous attempt failed ---


def test_failure_after_claiming_leaves_the_delivery_retryable_and_a_redelivery_succeeds(
    client, internal_headers, store, monkeypatch
):
    payload = pull_request_payload(repo_id=901, head_sha="h-retry")
    calls = {"n": 0}
    real_process_event = routes.process_event

    def flaky(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise ConnectionError("database blip with secret-ish detail")
        return real_process_event(*args, **kwargs)

    monkeypatch.setattr(routes, "process_event", flaky)

    first = _post(client, internal_headers, "retry-1", "pull_request", payload)
    assert first.status_code == 500
    assert first.json() == {"detail": "processing_failed"}  # never echoes the exception text
    assert store.get_delivery("retry-1")["status"] == "retryable"

    second = _post(client, internal_headers, "retry-1", "pull_request", payload)  # same delivery id
    assert second.status_code == 202
    assert second.json()["status"] == "accepted"  # NOT "duplicate_ignored"
    assert second.json()["review_run_id"] is not None
    assert store.get_delivery("retry-1")["status"] == "succeeded"
    assert store.get_delivery("retry-1")["attempts"] == 2


def test_delivery_is_not_marked_succeeded_when_processing_raised(
    client, internal_headers, store, monkeypatch
):
    def boom(*args, **kwargs):
        raise RuntimeError("x")

    monkeypatch.setattr(routes, "process_event", boom)
    _post(client, internal_headers, "never-ok", "pull_request", pull_request_payload(repo_id=902))
    assert store.get_delivery("never-ok")["status"] != "succeeded"


def test_bad_payload_is_recorded_failed_not_retryable_and_returns_400(client, internal_headers, store):
    resp = _post(client, internal_headers, "bad-1", "pull_request", {"action": "opened"})
    assert resp.status_code == 400
    assert store.get_delivery("bad-1")["status"] == "failed"


def test_concurrent_in_flight_delivery_is_reported_in_progress_not_reprocessed(
    client, internal_headers, store
):
    store.claim_delivery("busy-1", "pull_request", pull_request_payload(repo_id=903))  # someone owns it
    resp = _post(client, internal_headers, "busy-1", "pull_request", pull_request_payload(repo_id=903))
    assert resp.status_code == 202 and resp.json()["status"] == "in_progress"
    assert store.get_delivery("busy-1")["attempts"] == 1


def test_a_failure_recording_success_reports_500_so_the_sender_retries(
    client, internal_headers, store, monkeypatch
):
    real_mark = store.mark_delivery

    def failing_mark(delivery_id, outcome, error=None):
        if outcome == "succeeded":
            raise ConnectionError("db down")
        return real_mark(delivery_id, outcome, error)

    monkeypatch.setattr(store, "mark_delivery", failing_mark)
    resp = _post(client, internal_headers, "mark-fail", "pull_request", pull_request_payload(repo_id=904))
    assert resp.status_code == 500
    monkeypatch.setattr(store, "mark_delivery", real_mark)
    # Row is still `processing` (never `succeeded`), so a redelivery/sweeper reclaims it.
    assert store.get_delivery("mark-fail")["status"] == "processing"


def test_redelivery_of_the_same_commit_does_not_create_a_second_job(client, internal_headers, store):
    payload = pull_request_payload(repo_id=905, head_sha="same-head")
    r1 = _post(client, internal_headers, "rd-1", "pull_request", payload)
    r2 = _post(client, internal_headers, "rd-2", "pull_request", payload)  # different delivery, same code
    assert r1.json()["review_run_id"] == r2.json()["review_run_id"]


def test_new_commit_supersedes_the_pending_review_of_the_old_one(client, internal_headers, store):
    old = _post(
        client, internal_headers, "c-1", "pull_request",
        pull_request_payload(repo_id=906, head_sha="old-head", action="opened"),
    ).json()["review_run_id"]
    new = _post(
        client, internal_headers, "c-2", "pull_request",
        pull_request_payload(repo_id=906, head_sha="new-head", action="synchronize"),
    ).json()["review_run_id"]

    assert old != new
    assert store.get_review_run(old)["status"] == "superseded"
    assert store.get_review_run(new)["status"] == "pending"


# --- manual retry endpoint ---


def test_retry_endpoint_requeues_only_failed_runs(client, internal_headers, store):
    run_id = _post(
        client, internal_headers, "rt-1", "pull_request", pull_request_payload(repo_id=907)
    ).json()["review_run_id"]

    conflict = client.post(f"/internal/review-runs/{run_id}/retry", headers=internal_headers)
    assert conflict.status_code == 409  # pending, not failed

    claimed = store.claim_next_review_run(60)
    store.finalize_review_run(
        run_id, claimed["attempts"], status="failed", findings=[], analysis_meta=None,
        error_code="not_found", error_message="x", latency_ms=1,
    )
    ok = client.post(f"/internal/review-runs/{run_id}/retry", headers=internal_headers)
    assert ok.status_code == 200 and ok.json()["status"] == "pending"

    assert client.post("/internal/review-runs/nope/retry", headers=internal_headers).status_code == 404


def test_retry_endpoint_requires_the_internal_secret(client):
    assert client.post("/internal/review-runs/x/retry").status_code == 401

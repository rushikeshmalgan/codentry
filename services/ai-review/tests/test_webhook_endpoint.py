"""Full-stack tests through TestClient: auth, dedup, event routing, and the
pending -> running -> completed async lifecycle.

TestClient runs FastAPI BackgroundTasks synchronously as part of the
request/response cycle, so by the time client.post(...) returns, the
placeholder review has already completed — no polling needed.
"""

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


def test_pull_request_event_accepted_and_completes(client, internal_headers):
    resp = _post(client, internal_headers, "pr-1", "pull_request", pull_request_payload(action="opened"))

    assert resp.status_code == 202
    body = resp.json()
    assert body["status"] == "accepted"
    review_run_id = body["review_run_id"]
    assert review_run_id

    status_resp = client.get(f"/internal/review-runs/{review_run_id}", headers=internal_headers)
    status_body = status_resp.json()
    assert status_body["status"] == "completed"
    assert status_body["latency_ms"] is not None
    assert status_body["started_at"] is not None
    assert status_body["completed_at"] is not None
    assert status_body["error_message"] is None


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

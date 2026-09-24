from tests.github_payloads import pull_request_payload


def test_review_run_status_requires_internal_secret(client):
    resp = client.get("/internal/review-runs/some-id")
    assert resp.status_code == 401


def test_review_run_not_found_returns_404(client, internal_headers):
    resp = client.get("/internal/review-runs/does-not-exist", headers=internal_headers)
    assert resp.status_code == 404


def test_review_run_status_does_not_expose_secrets(client, internal_headers):
    create_resp = client.post(
        "/internal/webhook/pull-request",
        headers=internal_headers,
        json={"delivery_id": "d-status", "event_type": "pull_request", "payload": pull_request_payload()},
    )
    review_run_id = create_resp.json()["review_run_id"]

    resp = client.get(f"/internal/review-runs/{review_run_id}", headers=internal_headers)
    body = resp.json()

    assert set(body.keys()) == {
        "id",
        "pull_request_id",
        "trigger_event",
        "status",
        "head_sha",
        "base_sha",
        "merge_base_sha",
        "attempts",
        "started_at",
        "completed_at",
        "latency_ms",
        "error_code",
        "error_message",
        "analysis_meta",
    }
    # Nothing that could carry a credential or repository content.
    assert not any("secret" in key or "token" in key or "key" == key for key in body)

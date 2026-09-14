from tests.github_payloads import installation_payload


def test_list_installations_requires_internal_secret(client):
    resp = client.get("/internal/installations")
    assert resp.status_code == 401


def test_list_installations_empty_by_default(client, internal_headers):
    resp = client.get("/internal/installations", headers=internal_headers)
    assert resp.status_code == 200
    assert resp.json() == []


def test_list_installations_reflects_bookkeeping(client, internal_headers):
    client.post(
        "/internal/webhook/pull-request",
        headers=internal_headers,
        json={
            "delivery_id": "d-inst",
            "event_type": "installation",
            "payload": installation_payload(
                installation_id=55,
                login="octo-team",
                account_type="Organization",
                repos=[{"id": 1, "full_name": "octo-team/one"}],
            ),
        },
    )

    resp = client.get("/internal/installations", headers=internal_headers)
    data = resp.json()

    assert len(data) == 1
    assert data[0]["account_login"] == "octo-team"
    assert data[0]["account_type"] == "Organization"
    assert data[0]["github_installation_id"] == 55
    assert data[0]["repository_count"] == 1
    assert data[0]["repositories"] == [{"full_name": "octo-team/one", "is_active": True}]

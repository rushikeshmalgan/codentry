"""The Supabase Data API stays closed to the project's anon key.

Before migration 0005 it was open (measured on the local Supabase stack, see
docs/store-contract-tests.md): row level security was off on every Codentry table and the
anon role held table privileges, so anyone with the anon key (public by Supabase's
design) could read webhook payloads and insert, update or delete rows, including a
`retryable` webhook_deliveries row that the backend sweeper would then process without
any HMAC or internal-secret check. Migration 0005 enables RLS and revokes the anon /
authenticated privileges; these tests pin that, for reads and for every kind of write.

They need the local stack (services/ai-review/scripts/run_store_contract_tests.sh) and
skip without it.
"""

from __future__ import annotations

import os
import uuid

import httpx
import pytest

from tests.store_backends import KEY_ENV, supabase_test_settings

ANON_ENV = "CODENTRY_TEST_SUPABASE_ANON_KEY"
TABLES = (
    "installations",
    "repositories",
    "pull_requests",
    "review_runs",
    "webhook_deliveries",
    "findings",
)
DENIED = (401, 403)


@pytest.fixture()
def clients():
    """(anon, service_role) clients for the local stack's Data API."""
    settings = supabase_test_settings()
    anon_key = os.environ.get(ANON_ENV, "").strip()
    if settings is None or not anon_key:
        pytest.skip(f"set {ANON_ENV} and {KEY_ENV} for the local Supabase stack")
    url, service_key = settings

    def client(key: str) -> httpx.Client:
        return httpx.Client(
            base_url=f"{url}/rest/v1",
            headers={"apikey": key, "Authorization": f"Bearer {key}"},
            timeout=10,
        )

    with client(anon_key) as anon, client(service_key) as service:
        yield anon, service


@pytest.fixture()
def delivery(clients):
    """A real webhook_deliveries row, written by the service role, removed afterwards."""
    _, service = clients
    delivery_id = f"exposure-probe-{uuid.uuid4()}"
    created = service.post(
        "/webhook_deliveries",
        json={"delivery_id": delivery_id, "event_type": "probe", "status": "succeeded"},
    )
    assert created.status_code == 201, created.text
    yield delivery_id
    service.delete("/webhook_deliveries", params={"delivery_id": f"eq.{delivery_id}"})


def _event_type(service: httpx.Client, delivery_id: str) -> list[dict]:
    response = service.get(
        "/webhook_deliveries",
        params={"delivery_id": f"eq.{delivery_id}", "select": "event_type"},
    )
    assert response.status_code == 200, response.text
    return response.json()


@pytest.mark.parametrize("table", TABLES)
def test_the_anon_key_cannot_read_a_codentry_table(clients, table):
    anon, _ = clients
    response = anon.get(f"/{table}", params={"select": "id", "limit": "1"})
    assert response.status_code in DENIED, response.status_code


def test_the_service_role_still_reads_what_the_anon_key_cannot(clients, delivery):
    """The lockdown must not lock out the backend (it uses the service_role key)."""
    _, service = clients
    assert _event_type(service, delivery) == [{"event_type": "probe"}]


def test_the_anon_key_cannot_insert_a_webhook_delivery(clients):
    anon, service = clients
    delivery_id = f"anon-insert-probe-{uuid.uuid4()}"
    try:
        response = anon.post(
            "/webhook_deliveries",
            json={"delivery_id": delivery_id, "event_type": "probe", "status": "retryable"},
        )
    finally:
        # Never leave a probe row behind for the sweeper, whatever the outcome.
        service.delete("/webhook_deliveries", params={"delivery_id": f"eq.{delivery_id}"})
    assert response.status_code in DENIED, response.status_code


def test_the_anon_key_cannot_update_a_row(clients, delivery):
    anon, service = clients
    response = anon.patch(
        "/webhook_deliveries",
        params={"delivery_id": f"eq.{delivery}"},
        json={"event_type": "tampered"},
    )
    assert response.status_code in DENIED, response.status_code
    assert _event_type(service, delivery) == [{"event_type": "probe"}]


def test_the_anon_key_cannot_delete_a_row(clients, delivery):
    anon, service = clients
    response = anon.delete("/webhook_deliveries", params={"delivery_id": f"eq.{delivery}"})
    assert response.status_code in DENIED, response.status_code
    assert _event_type(service, delivery) == [{"event_type": "probe"}]

"""Can the project's anon key reach Codentry's tables through the Supabase Data API?

Measured on the local Supabase stack (docs/store-contract-tests.md), with migrations
0001-0004 applied: YES. Row level security is off on every Codentry table and the anon
role holds table privileges, so anyone with the anon key (public by Supabase's design)
can read webhook payloads, and insert, update or delete rows, including a
`webhook_deliveries` row that the backend sweeper would then process without any HMAC
or internal-secret check. See docs/architecture.md, known gap #10.

These tests assert the SAFE behavior and are marked xfail(strict=True): today they
document the gap; the day a migration closes it they fail loudly, so the marker must be
removed in the same change. They need the local stack and skip without it.
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
KNOWN_GAP = (
    "known gap: RLS is off and anon holds table privileges in migrations 0001-0004 "
    "(docs/architecture.md gap #10); remove this marker when a migration closes it"
)


def _clients() -> tuple[httpx.Client, httpx.Client]:
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

    return client(anon_key), client(service_key)


@pytest.mark.xfail(strict=True, reason=KNOWN_GAP)
@pytest.mark.parametrize("table", TABLES)
def test_the_anon_key_cannot_read_a_codentry_table(table):
    anon, service = _clients()
    with anon, service:
        response = anon.get(f"/{table}", params={"select": "id", "limit": "1"})
    assert response.status_code in (401, 403), response.status_code


@pytest.mark.xfail(strict=True, reason=KNOWN_GAP)
def test_the_anon_key_cannot_insert_a_webhook_delivery():
    delivery_id = f"anon-insert-probe-{uuid.uuid4()}"
    anon, service = _clients()
    with anon, service:
        try:
            response = anon.post(
                "/webhook_deliveries",
                json={"delivery_id": delivery_id, "event_type": "probe", "status": "retryable"},
            )
        finally:
            # Never leave a probe row behind for the sweeper, whatever the outcome.
            service.delete("/webhook_deliveries", params={"delivery_id": f"eq.{delivery_id}"})
    assert response.status_code in (401, 403), response.status_code

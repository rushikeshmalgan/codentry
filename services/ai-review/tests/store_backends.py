"""Store backends for the store contract tests.

The same state-machine tests run against `InMemoryReviewStore` and, when a local Supabase
stack is available, against `SupabaseReviewStore` over a real Postgres + PostgREST with
supabase/migrations/0001-0004 applied (docs/store-contract-tests.md).

Safety: the Supabase backend DELETES every row of the Codentry tables before each test,
so it only ever runs against a local stack:

- it reads its own variables (CODENTRY_TEST_SUPABASE_URL / _SERVICE_ROLE_KEY), never the
  service's SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY, so a production configuration in
  the environment can never be picked up by accident;
- it refuses any URL whose host is not loopback.
"""

from __future__ import annotations

import os
from urllib.parse import urlparse

from app.store import InMemoryReviewStore, ReviewStore, SupabaseReviewStore

URL_ENV = "CODENTRY_TEST_SUPABASE_URL"
KEY_ENV = "CODENTRY_TEST_SUPABASE_SERVICE_ROLE_KEY"
_LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}

# Children before parents (foreign keys): findings -> review_runs -> pull_requests ->
# repositories -> installations. webhook_deliveries has no foreign keys.
_TABLES_IN_DELETE_ORDER = (
    "findings",
    "review_runs",
    "pull_requests",
    "repositories",
    "installations",
    "webhook_deliveries",
)
_NIL_UUID = "00000000-0000-0000-0000-000000000000"

SKIP_REASON = (
    f"set {URL_ENV} and {KEY_ENV} to run against a local Supabase stack "
    "(docs/store-contract-tests.md)"
)


class UnsafeTestDatabaseError(RuntimeError):
    """The configured test database is not local; wiping it is refused."""


def supabase_test_settings() -> tuple[str, str] | None:
    """(url, key) for the local test stack, or None when it is not configured."""
    url = os.environ.get(URL_ENV, "").strip()
    key = os.environ.get(KEY_ENV, "").strip()
    if not url or not key:
        return None
    host = urlparse(url).hostname
    if host not in _LOOPBACK_HOSTS:
        raise UnsafeTestDatabaseError(
            f"{URL_ENV} points at {host!r}; the contract tests delete every row they can "
            "reach, so they only run against a loopback (local) Supabase stack"
        )
    return url, key


def wipe(store: SupabaseReviewStore) -> None:
    """Delete every row of the Codentry tables (PostgREST requires a filter on DELETE)."""
    client = store._client  # test-only access to the store's own client
    for table in _TABLES_IN_DELETE_ORDER:
        client.table(table).delete().neq("id", _NIL_UUID).execute()


def make_store(kind: str) -> ReviewStore | None:
    """A fresh, empty store of the given kind, or None if `supabase` is not configured."""
    if kind == "memory":
        return InMemoryReviewStore()
    if kind != "supabase":
        raise ValueError(f"unknown store kind {kind!r}")
    settings = supabase_test_settings()
    if settings is None:
        return None
    store = SupabaseReviewStore(*settings)
    wipe(store)
    return store

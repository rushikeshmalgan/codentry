import os

# Must be set before `app.main` is imported anywhere, since Settings is
# cached via lru_cache at import time.
os.environ.setdefault("CODENTRY_INTERNAL_WEBHOOK_SECRET", "test-internal-secret-do-not-use-in-prod")
os.environ.setdefault("ENVIRONMENT", "test")
# Tests drive the worker explicitly; a background poller would race them.
os.environ.setdefault("WORKER_ENABLED", "false")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
from app.store import InMemoryReviewStore, get_store  # noqa: E402

INTERNAL_SECRET = "test-internal-secret-do-not-use-in-prod"


@pytest.fixture()
def anyio_backend():
    return "asyncio"


@pytest.fixture()
def store():
    return InMemoryReviewStore()


@pytest.fixture()
def client(store):
    app.dependency_overrides[get_store] = lambda: store
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture()
def internal_headers():
    return {"X-Codentry-Internal-Secret": INTERNAL_SECRET}

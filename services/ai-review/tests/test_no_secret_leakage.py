"""Asserts the internal secret never appears in log output for either an
accepted or a rejected request. Doesn't prove no secret is EVER logged
anywhere (that would need static analysis of every log call), but exercises
the two request paths most likely to be tempted to log a header value.
"""

import logging

from tests.conftest import INTERNAL_SECRET
from tests.github_payloads import pull_request_payload


def test_internal_secret_not_logged_on_success(client, internal_headers, caplog):
    with caplog.at_level(logging.DEBUG):
        client.post(
            "/internal/webhook/pull-request",
            headers=internal_headers,
            json={
                "delivery_id": "secret-check-1",
                "event_type": "pull_request",
                "payload": pull_request_payload(),
            },
        )

    for record in caplog.records:
        assert INTERNAL_SECRET not in record.getMessage()


def test_internal_secret_not_logged_on_rejection(client, caplog):
    with caplog.at_level(logging.DEBUG):
        client.post(
            "/internal/webhook/pull-request",
            headers={"X-Codentry-Internal-Secret": "some-wrong-guess"},
            json={"delivery_id": "secret-check-2", "event_type": "pull_request", "payload": {}},
        )

    for record in caplog.records:
        assert "some-wrong-guess" not in record.getMessage()
        assert INTERNAL_SECRET not in record.getMessage()

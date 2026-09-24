"""LOCAL / MOCKED end-to-end test of the whole Phase 0 pipeline.

    signed-off webhook payload (TestClient, internal secret)
        -> durable delivery + idempotent bookkeeping + pending job row
        -> ReviewWorker.run_once() claims the job
        -> REAL snapshot fetcher (analysis/changed_files.py) against a FAKE GitHub
           (respx mock: pinned refs, pagination, merge base, blob checks)
        -> REAL ESLint + REAL Semgrep on the fetched content
        -> differential classification -> fenced finalize -> stored findings

WHAT THIS IS NOT: verification against real GitHub, a real GitHub App, real
Supabase, or a deployed service. Everything outside the process is mocked or
in-memory. It proves our pipeline logic composes; it says nothing about
GitHub's actual behavior, Postgres semantics, Render, or free-tier limits.
The real end-to-end run remains USER ACTION REQUIRED
(docs/first-deployment-runbook.md).
"""

import respx

from app.worker import ReviewWorker
from tests.fake_github import FakeGitHub, entry, private_key_pem
from tests.github_payloads import pull_request_payload as _payload
from tests.job_helpers import configured_settings

BASE_A = "function f() {\n  var legacy = 1;\n  return 2;\n}\nmodule.exports = { f };\n"
HEAD_A = (
    "// added header\n"
    "function f() {\n  var legacy = 1;\n  return 2;\n}\n"
    "function g(input) {\n  return eval(input);\n}\n"
    "module.exports = { f, g };\n"
)
PATCH_A = (
    "@@ -1,5 +1,9 @@\n+// added header\n function f() {\n   var legacy = 1;\n   return 2;\n }\n"
    "+function g(input) {\n+  return eval(input);\n+}\n-module.exports = { f };\n"
    "+module.exports = { f, g };\n"
)


def _pr(**kw):
    # The fake GitHub serves octo/widgets; installation 999 matches its token route.
    return _payload(repo_full_name="octo/widgets", **kw)


def _post(client, headers, delivery_id, payload):
    return client.post(
        "/internal/webhook/pull-request",
        headers=headers,
        json={"delivery_id": delivery_id, "event_type": "pull_request", "payload": payload},
    )


def _github_for_the_pr(tmp_path) -> FakeGitHub:
    marker = tmp_path / "pr_config_executed.txt"
    evil_config = (
        f"require('fs').writeFileSync({str(marker).replace(chr(92), '/')!r}, 'pwned');\n"
        "module.exports = { rules: {} };\n"
    )
    gh = FakeGitHub(head="H2", base="B1", merge_base="MB1")
    gh.listing = [
        entry("src/a.js", "modified", sha="blobA", patch=PATCH_A),
        entry("src/new.js", "added", sha="blobN", patch="@@ -0,0 +1 @@\n+var unusedNew = 1;\n"),
        entry(".eslintrc.js", "added", sha="blobC", patch="@@ -0,0 +1,2 @@\n+x\n+y\n"),
        entry("docs/readme.md", "modified"),
    ]
    gh.add_file("src/a.js", "H2", HEAD_A, "blobA")
    gh.add_file("src/a.js", "MB1", BASE_A)
    gh.add_file("src/new.js", "H2", "var unusedNew = 1;\n", "blobN")
    gh.add_file(".eslintrc.js", "H2", evil_config, "blobC")  # never fetched, never executed
    gh.marker = marker
    return gh


def test_local_mocked_pipeline_webhook_to_stored_differential_findings(
    client, internal_headers, store, tmp_path
):
    gh = _github_for_the_pr(tmp_path)
    settings = configured_settings(github_private_key=private_key_pem())

    # 1) webhook -> durable delivery + pending job pinned to head H2
    resp = _post(
        client, internal_headers, "e2e-1",
        _pr(head_sha="H2", base_sha="B1", installation_id=999, pr_number=1),
    )
    assert resp.status_code == 202 and resp.json()["status"] == "accepted"
    run_id = resp.json()["review_run_id"]
    assert store.get_review_run(run_id)["status"] == "pending"
    assert store.get_delivery("e2e-1")["status"] == "succeeded"

    # 2) the worker claims and executes it against the fake GitHub
    with respx.mock as mock:
        gh.mount(mock)
        worked = ReviewWorker(store, settings).run_once()
    assert worked is True

    # 3) results, read back through the public internal API
    status = client.get(f"/internal/review-runs/{run_id}", headers=internal_headers).json()
    assert status["status"] == "completed", status
    assert status["head_sha"] == "H2" and status["merge_base_sha"] == "MB1"
    assert status["attempts"] == 1 and status["error_code"] is None

    findings = store.get_findings_for_review_run(run_id)
    by = {(f["file_path"], f["title"], f["change_status"]): f for f in findings}

    # pre-existing unused var (drifted down one line), not blamed on the PR
    legacy = by[("src/a.js", "no-unused-vars", "existing")]
    assert legacy["start_line"] == 3 and legacy["base_start_line"] == 2 and legacy["in_diff"] is False
    # introduced by the PR
    assert by[("src/a.js", "eval-usage", "new")]["in_diff"] is True
    assert by[("src/new.js", "no-unused-vars", "new")]["in_diff"] is True
    assert {f["change_status"] for f in findings} == {"new", "existing"}
    assert all(f["identity_key"] and f["dedup_hash"] for f in findings)

    # pinned reads only; the PR's own config was neither fetched nor executed
    refs = {ref for _, ref in gh.content_requests}
    assert refs == {"H2", "MB1", "B1"}
    assert not gh.marker.exists(), "PR-supplied .eslintrc.js was executed"
    assert ("src/a.js", "MB1") in gh.content_requests and ("src/a.js", "H2") in gh.content_requests

    meta = status["analysis_meta"]
    assert meta["head"]["config_source"] == "baseline"
    assert meta["differential"]["new"] == 2 and meta["differential"]["existing"] == 1
    assert meta["head"]["semgrep_version"] and meta["head"]["eslint_version"]

    # 4) redelivery of the same webhook is a duplicate; same commit is not re-reviewed
    again = _post(
        client, internal_headers, "e2e-1",
        _pr(head_sha="H2", base_sha="B1", installation_id=999, pr_number=1),
    )
    assert again.json()["status"] == "duplicate_ignored"
    other_delivery = _post(
        client, internal_headers, "e2e-2",
        _pr(head_sha="H2", base_sha="B1", installation_id=999, pr_number=1),
    )
    assert other_delivery.json()["review_run_id"] == run_id


def test_local_mocked_pipeline_supersedes_a_review_whose_head_moved(
    client, internal_headers, store, tmp_path
):
    gh = _github_for_the_pr(tmp_path)
    gh.head_sequence = ["H3-newer-than-the-event"]  # GitHub already has a newer commit
    settings = configured_settings(github_private_key=private_key_pem())

    run_id = _post(
        client, internal_headers, "e2e-stale",
        _pr(head_sha="H2", base_sha="B1", installation_id=999, pr_number=1),
    ).json()["review_run_id"]

    with respx.mock as mock:
        gh.mount(mock)
        ReviewWorker(store, settings).run_once()

    stored = store.get_review_run(run_id)
    assert stored["status"] == "superseded" and stored["error_code"] == "superseded_by_newer_head"
    assert store.get_findings_for_review_run(run_id) == []
    assert gh.content_requests == []  # bailed before reading any file content


def test_local_mocked_pipeline_transient_github_outage_is_retried_not_lost(
    client, internal_headers, store, tmp_path
):
    import httpx

    gh = _github_for_the_pr(tmp_path)
    gh.pull_response = httpx.Response(503, json={"message": "GitHub is having a moment"})
    settings = configured_settings(github_private_key=private_key_pem())

    run_id = _post(
        client, internal_headers, "e2e-outage",
        _pr(head_sha="H2", base_sha="B1", installation_id=999, pr_number=1),
    ).json()["review_run_id"]

    with respx.mock as mock:
        gh.mount(mock)
        ReviewWorker(store, settings).run_once()

    stored = store.get_review_run(run_id)
    assert stored["status"] == "pending"  # requeued with backoff, not failed, not lost
    assert stored["error_code"] == "server" and stored["attempts"] == 1

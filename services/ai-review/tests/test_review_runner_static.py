"""Direct, isolated tests of run_static_review's branching — not routed
through HTTP/auth/event-routing (that's test_webhook_endpoint.py's job).
"""

from analysis import eslint_runner, semgrep_runner
from analysis.changed_files import ChangedFilesError
from analysis.workspace import SourceFile
from app import review_runner
from app.config import get_settings


def _make_pending_run(store):
    inst = store.upsert_installation(1, "octo", "Organization")
    repo = store.upsert_repository(inst["id"], 100, "octo/widgets", "main")
    pr = store.upsert_pull_request(repo["id"], 1, "t", "dev", "abc", "def", "open")
    return store.create_review_run(pr["id"], "opened")


def test_fails_cleanly_when_github_app_not_configured(store, monkeypatch):
    monkeypatch.delenv("GITHUB_APP_ID", raising=False)
    monkeypatch.delenv("GITHUB_PRIVATE_KEY", raising=False)
    get_settings.cache_clear()

    run = _make_pending_run(store)
    review_runner.run_static_review(store, run["id"], 1, "octo/widgets", 1)

    updated = store.get_review_run(run["id"])
    assert updated["status"] == "failed"
    assert "github_app_not_configured" in updated["error_message"]
    assert store.get_findings_for_review_run(run["id"]) == []
    get_settings.cache_clear()


def test_fails_cleanly_when_changed_files_fetch_raises(store, monkeypatch):
    monkeypatch.setenv("GITHUB_APP_ID", "1")
    monkeypatch.setenv("GITHUB_PRIVATE_KEY", "key")
    get_settings.cache_clear()

    async def raise_fetch(**kwargs):
        raise ChangedFilesError("simulated GitHub outage")

    monkeypatch.setattr(review_runner, "fetch_changed_files", raise_fetch)

    run = _make_pending_run(store)
    try:
        review_runner.run_static_review(store, run["id"], 1, "octo/widgets", 1)
    finally:
        get_settings.cache_clear()

    updated = store.get_review_run(run["id"])
    assert updated["status"] == "failed"
    assert "changed_files_fetch_failed" in updated["error_message"]


def test_completes_with_real_findings_persisted(store, monkeypatch):
    monkeypatch.setenv("GITHUB_APP_ID", "1")
    monkeypatch.setenv("GITHUB_PRIVATE_KEY", "key")
    get_settings.cache_clear()

    # Reuses the calibrated eslint_sample.js fixture content (exactly 2
    # findings: no-unused-vars, no-undef) — `process` must be exported or
    # ESLint also flags the function itself as unused, throwing off the count.
    content = (
        "function process(data) {\n"
        "  const unusedVar = 1;\n"
        "  return missingGlobal(data);\n"
        "}\n\n"
        "module.exports = { process };\n"
    )

    async def fake_fetch(**kwargs):
        return [SourceFile(path="bad.js", content=content)]

    monkeypatch.setattr(review_runner, "fetch_changed_files", fake_fetch)

    run = _make_pending_run(store)
    try:
        review_runner.run_static_review(store, run["id"], 1, "octo/widgets", 1)
    finally:
        get_settings.cache_clear()

    updated = store.get_review_run(run["id"])
    assert updated["status"] == "completed"
    assert updated["error_message"] is None
    assert updated["latency_ms"] is not None

    findings = store.get_findings_for_review_run(run["id"])
    assert len(findings) == 2
    assert {f["source"] for f in findings} == {"ESLINT"}


def test_completes_with_zero_findings_for_clean_content(store, monkeypatch):
    monkeypatch.setenv("GITHUB_APP_ID", "1")
    monkeypatch.setenv("GITHUB_PRIVATE_KEY", "key")
    get_settings.cache_clear()

    async def fake_fetch(**kwargs):
        # Must export `add`, or ESLint's no-unused-vars flags the function
        # itself and this is no longer "clean" content.
        return [
            SourceFile(
                path="clean.js",
                content="function add(a, b) {\n  return a + b;\n}\n\nmodule.exports = { add };\n",
            )
        ]

    monkeypatch.setattr(review_runner, "fetch_changed_files", fake_fetch)

    run = _make_pending_run(store)
    try:
        review_runner.run_static_review(store, run["id"], 1, "octo/widgets", 1)
    finally:
        get_settings.cache_clear()

    updated = store.get_review_run(run["id"])
    assert updated["status"] == "completed"
    assert store.get_findings_for_review_run(run["id"]) == []


def test_partial_tool_failure_still_completes_with_error_noted(store, monkeypatch):
    monkeypatch.setenv("GITHUB_APP_ID", "1")
    monkeypatch.setenv("GITHUB_PRIVATE_KEY", "key")
    get_settings.cache_clear()

    async def fake_fetch(**kwargs):
        return [SourceFile(path="bad.js", content="const x = eval('1');\n")]

    monkeypatch.setattr(review_runner, "fetch_changed_files", fake_fetch)
    real_which = semgrep_runner.shutil.which
    monkeypatch.setattr(
        semgrep_runner.shutil, "which", lambda name: None if name == "semgrep" else real_which(name)
    )

    run = _make_pending_run(store)
    try:
        review_runner.run_static_review(store, run["id"], 1, "octo/widgets", 1)
    finally:
        get_settings.cache_clear()

    updated = store.get_review_run(run["id"])
    # Overall status maps partial_failure -> "completed" in the DB (findings
    # from the tool that DID run are real and worth keeping), with the
    # partial failure surfaced via error_message rather than hidden.
    assert updated["status"] == "completed"
    assert updated["error_message"] is not None
    assert "semgrep" in updated["error_message"].lower()


def test_full_tool_failure_marks_review_run_failed(store, monkeypatch):
    monkeypatch.setenv("GITHUB_APP_ID", "1")
    monkeypatch.setenv("GITHUB_PRIVATE_KEY", "key")
    get_settings.cache_clear()

    async def fake_fetch(**kwargs):
        return [SourceFile(path="bad.js", content="const x = eval('1');\n")]

    monkeypatch.setattr(review_runner, "fetch_changed_files", fake_fetch)
    monkeypatch.setattr(eslint_runner.shutil, "which", lambda _name: None)
    monkeypatch.setattr(semgrep_runner.shutil, "which", lambda _name: None)

    run = _make_pending_run(store)
    try:
        review_runner.run_static_review(store, run["id"], 1, "octo/widgets", 1)
    finally:
        get_settings.cache_clear()

    updated = store.get_review_run(run["id"])
    assert updated["status"] == "failed"

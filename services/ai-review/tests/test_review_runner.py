"""execute_review_run: pinned snapshot -> differential analysis -> fenced finalize.

Real ESLint and Semgrep run against the in-memory file contents; only the
GitHub fetch is replaced (a fake fetcher). That makes these LOCAL/MOCKED tests
— they prove the pipeline logic, not real GitHub behavior.
"""

from datetime import timedelta

from analysis import eslint_runner, semgrep_runner
from analysis.changed_files import HeadMovedError, SnapshotError
from app import review_runner
from app.review_runner import backoff_seconds, execute_review_run
from app.store import _parse
from tests.job_helpers import (
    changed,
    claim,
    configured_settings,
    enqueue,
    fake_fetcher,
    now,
    snapshot,
)

BASE_SRC = "function f() {\n  var legacy = 1;\n  return 2;\n}\nmodule.exports = { f };\n"
# Two comment lines inserted above (line drift) + a brand-new eval() call.
HEAD_SRC = (
    "// header\n// header 2\n"
    "function f() {\n  var legacy = 1;\n  return 2;\n}\n"
    "function g(x) {\n  return eval(x);\n}\n"
    "module.exports = { f, g };\n"
)
HEAD_PATCH = (
    "@@ -1,5 +1,10 @@\n+// header\n+// header 2\n function f() {\n   var legacy = 1;\n"
    "   return 2;\n }\n+function g(x) {\n+  return eval(x);\n+}\n-module.exports = { f };\n"
    "+module.exports = { f, g };\n"
)


def _claimed(store, **kw):
    run, _ = enqueue(store, **kw)
    return claim(store)


def test_differential_run_separates_new_from_preexisting_findings(store):
    run = _claimed(store)
    snap = snapshot([changed("src/a.js", base=BASE_SRC, head=HEAD_SRC, patch=HEAD_PATCH)])

    status = execute_review_run(store, run, configured_settings(), fake_fetcher(snap))

    assert status == "completed"
    stored = store.get_review_run(run["id"])
    assert stored["status"] == "completed" and stored["error_code"] is None
    assert stored["merge_base_sha"] == "merge-aaa"
    assert stored["latency_ms"] is not None

    findings = store.get_findings_for_review_run(run["id"])
    by = {(f["title"], f["change_status"]): f for f in findings}

    # The unused `legacy` var existed before the PR and merely drifted down 2 lines.
    legacy = by[("no-unused-vars", "existing")]
    assert legacy["start_line"] == 4 and legacy["base_start_line"] == 2
    assert legacy["in_diff"] is False and legacy["moved"] is False
    # eval() was introduced by the PR.
    new_eval = by[("eval-usage", "new")]
    assert new_eval["in_diff"] is True and new_eval["start_line"] == 8
    assert not any(k[1] == "fixed" for k in by)

    meta = stored["analysis_meta"]
    assert meta["differential"]["new"] >= 1 and meta["differential"]["existing"] >= 1
    assert meta["snapshot"]["head_sha"] == "head-aaa"
    assert meta["head"]["ruleset_sha256"] and meta["head"]["eslint_version"]
    assert meta["head"]["config_source"] == "baseline"


def test_finding_fixed_by_the_pr_is_recorded_as_fixed(store):
    run = _claimed(store)
    fixed_head = "function f() {\n  return 2;\n}\nmodule.exports = { f };\n"
    snap = snapshot([changed("src/a.js", base=BASE_SRC, head=fixed_head)])

    assert execute_review_run(store, run, configured_settings(), fake_fetcher(snap)) == "completed"

    statuses = {f["change_status"] for f in store.get_findings_for_review_run(run["id"])}
    assert statuses == {"fixed"}


def test_new_file_findings_are_all_new(store):
    run = _claimed(store)
    snap = snapshot([changed("src/new.js", head="var x = eval('1');\n")])
    execute_review_run(store, run, configured_settings(), fake_fetcher(snap))
    findings = store.get_findings_for_review_run(run["id"])
    assert findings and {f["change_status"] for f in findings} == {"new"}


def test_clean_pr_completes_with_zero_findings(store):
    run = _claimed(store)
    clean = "function add(a, b) {\n  return a + b;\n}\nmodule.exports = { add };\n"
    snap = snapshot([changed("src/c.js", base=clean, head=clean + "\n")])
    assert execute_review_run(store, run, configured_settings(), fake_fetcher(snap)) == "completed"
    assert store.get_findings_for_review_run(run["id"]) == []


def test_pr_cannot_change_its_own_review_rules(store):
    """A PR that ships .eslintrc.js / .eslintrc.json / .eslintignore turning
    everything off still gets the baseline. Control files are recorded as
    skipped (benign), never applied."""
    run = _claimed(store)
    src = "var unused = 1;\n"
    snap = snapshot(
        [
            changed("src/a.js", head=src),
            changed(".eslintrc.json", head='{"root": true, "rules": {"no-unused-vars": "off"}}'),
            changed(".eslintrc.js", head="module.exports = { rules: {} };"),
            changed(".eslintignore", head="*.js\n"),
        ]
    )
    assert execute_review_run(store, run, configured_settings(), fake_fetcher(snap)) == "completed"
    titles = {f["title"] for f in store.get_findings_for_review_run(run["id"])}
    assert "no-unused-vars" in titles
    meta = store.get_review_run(run["id"])["analysis_meta"]
    assert meta["head"]["config_source"] == "baseline"
    assert meta["head"]["skipped_by_reason"]["control_file"] == 3


def test_trusted_base_config_is_applied_to_both_sides(store):
    run = _claimed(store)
    snap = snapshot(
        [changed("src/a.js", base="console.log('a');\n", head="console.log('a');\nconsole.log('b');\n")],
        config_text='{"rules": {"no-console": "error"}, "env": {"node": true}}',
    )
    execute_review_run(store, run, configured_settings(), fake_fetcher(snap))
    findings = [f for f in store.get_findings_for_review_run(run["id"]) if f["title"] == "no-console"]
    assert {f["change_status"] for f in findings} == {"new", "existing"}
    meta = store.get_review_run(run["id"])["analysis_meta"]
    assert meta["head"]["config_source"] == "baseline+base_overlay"
    assert meta["base"]["config_source"] == "baseline+base_overlay"


def test_unavailable_base_content_leaves_findings_unclassified_and_run_partial(store):
    run = _claimed(store)
    snap = snapshot(
        [changed("src/a.js", head="var unused = 1;\n", status="modified", base_unavailable=True)],
        skipped=[{"path": "src/a.js", "reason": "base_unavailable"}],
    )
    status = execute_review_run(store, run, configured_settings(), fake_fetcher(snap))

    assert status == "partial"
    findings = store.get_findings_for_review_run(run["id"])
    assert findings and all(f["change_status"] is None for f in findings)  # never guessed "new"
    stored = store.get_review_run(run["id"])
    assert stored["status"] == "partial" and stored["error_code"] == "differential_incomplete"
    assert stored["analysis_meta"]["differential"]["unclassified"] == len(findings)


def test_skipped_oversized_file_makes_the_run_partial_not_completed(store):
    run = _claimed(store)
    snap = snapshot(
        [changed("src/a.js", head="var x = 1;\nmodule.exports = { x };\n")],
        skipped=[{"path": "src/huge.js", "reason": "too_large"}],
    )
    assert execute_review_run(store, run, configured_settings(), fake_fetcher(snap)) == "partial"
    assert "snapshot_skipped_files" in store.get_review_run(run["id"])["analysis_meta"]["incomplete_reasons"]


def test_one_tool_unavailable_is_partial(store, monkeypatch):
    real_which = semgrep_runner.shutil.which
    monkeypatch.setattr(
        semgrep_runner.shutil,
        "which",
        lambda name, *a, **k: None if name == "semgrep" else real_which(name, *a, **k),
    )
    run = _claimed(store)
    snap = snapshot([changed("src/a.js", head="var unused = 1;\n")])
    status = execute_review_run(store, run, configured_settings(), fake_fetcher(snap))
    assert status == "partial"
    assert "semgrep" in store.get_review_run(run["id"])["error_message"].lower()


def test_both_tools_unavailable_fails_the_run(store, monkeypatch):
    monkeypatch.setattr(eslint_runner.shutil, "which", lambda *a, **k: None)
    monkeypatch.setattr(semgrep_runner.shutil, "which", lambda *a, **k: None)
    run = _claimed(store)
    snap = snapshot([changed("src/a.js", head="var x = 1;\n")])
    assert execute_review_run(store, run, configured_settings(), fake_fetcher(snap)) == "failed"
    assert store.get_review_run(run["id"])["error_code"] == "analysis_failed"


# --- failure classification -------------------------------------------------


def test_fails_cleanly_when_github_app_is_not_configured(store):
    run = _claimed(store)
    fetcher = fake_fetcher(snapshot([]))
    settings = configured_settings(github_app_id=None, github_private_key=None)

    assert execute_review_run(store, run, settings, fetcher) == "failed"

    stored = store.get_review_run(run["id"])
    assert stored["error_code"] == "github_app_not_configured"
    assert fetcher.calls == []  # never tried to reach GitHub
    assert store.get_findings_for_review_run(run["id"]) == []


def test_permanent_snapshot_error_fails_without_retry(store):
    run = _claimed(store)
    error = SnapshotError("not_found", "get pull request returned 404")
    assert execute_review_run(store, run, configured_settings(), fake_fetcher(error=error)) == "failed"
    stored = store.get_review_run(run["id"])
    assert stored["status"] == "failed" and stored["error_code"] == "not_found"


def test_too_many_files_fails_loudly_instead_of_a_partial_review(store):
    run = _claimed(store)
    error = SnapshotError("too_many_files", "300 analyzable changed files > limit 200")
    assert execute_review_run(store, run, configured_settings(), fake_fetcher(error=error)) == "failed"
    assert store.get_review_run(run["id"])["error_code"] == "too_many_files"
    assert store.get_findings_for_review_run(run["id"]) == []


def test_transient_error_requeues_with_backoff_then_fails_when_exhausted(store):
    run, _ = enqueue(store)
    error = SnapshotError("server", "list pull request files returned 502", retryable=True)
    settings = configured_settings()

    outcomes = []
    for _ in range(3):
        claimed = claim(store)
        assert claimed is not None
        outcomes.append(execute_review_run(store, claimed, settings, fake_fetcher(error=error)))
        # Backing off (or failed): not immediately claimable again.
        assert claim(store) is None
        # Simulate the backoff elapsing.
        if store.get_review_run(run["id"])["status"] == "pending":
            store.update_review_run(run["id"], available_at=(now() - timedelta(seconds=1)).isoformat())

    assert outcomes == ["pending", "pending", "failed"]
    stored = store.get_review_run(run["id"])
    assert stored["status"] == "failed" and stored["attempts"] == 3
    assert stored["error_code"] == "server"


def test_rate_limit_retry_after_is_honored(store):
    run, _ = enqueue(store)
    claimed = claim(store)
    error = SnapshotError("rate_limited", "rate limited", retryable=True, retry_after=3000)

    execute_review_run(store, claimed, configured_settings(), fake_fetcher(error=error))

    stored = store.get_review_run(run["id"])
    assert stored["status"] == "pending"
    wait = _parse(stored["available_at"]) - now()
    assert wait > timedelta(seconds=2900)  # honors Retry-After, not the 30s default backoff
    assert claim(store) is None


def test_backoff_is_exponential_and_capped():
    assert backoff_seconds(1) == 30 and backoff_seconds(2) == 60 and backoff_seconds(3) == 120
    assert backoff_seconds(30) == 900
    assert backoff_seconds(1, retry_after=500) == 500


def test_error_messages_never_carry_credentials(store):
    run = _claimed(store)
    error = SnapshotError("server", "boom ghp_abcdefghijklmnopqrstuvwxyz0123456789", retryable=False)
    execute_review_run(store, run, configured_settings(), fake_fetcher(error=error))
    assert "ghp_" not in store.get_review_run(run["id"])["error_message"]


# --- staleness / superseding ---------------------------------------------------


def test_head_moved_during_fetch_supersedes_the_run(store):
    run = _claimed(store)
    error = HeadMovedError("head-aaa", "head-bbb")
    assert execute_review_run(store, run, configured_settings(), fake_fetcher(error=error)) == "superseded"
    stored = store.get_review_run(run["id"])
    assert stored["status"] == "superseded" and stored["error_code"] == "superseded_by_newer_head"
    assert store.get_findings_for_review_run(run["id"]) == []


def test_run_for_an_old_head_is_superseded_before_any_github_call(store):
    old_run, _ = enqueue(store, head_sha="head-old", updated_at="2026-01-01T10:00:00Z")
    # A newer commit arrives while the old run is already claimed and running.
    old_claimed = claim(store)
    enqueue(store, head_sha="head-new", updated_at="2026-01-01T11:00:00Z", delivery_id="d-2")
    fetcher = fake_fetcher(snapshot([]))

    assert execute_review_run(store, old_claimed, configured_settings(), fetcher) == "superseded"
    assert fetcher.calls == []
    assert store.get_review_run(old_run["id"])["status"] == "superseded"


def test_head_advancing_during_analysis_is_caught_before_commit(store, monkeypatch):
    run = _claimed(store)
    pr = store.get_pull_request(run["pull_request_id"])
    snap = snapshot([changed("src/a.js", head="var unused = 1;\n")])

    real_analyze = review_runner.analyze_snapshot

    def analyze_then_push(snapshot_, ctx):
        outcome = real_analyze(snapshot_, ctx)
        # ...a new commit lands while ESLint/Semgrep were running.
        store.upsert_pull_request(
            pr["repository_id"], pr["github_pr_number"], "t", "dev", "head-newer", "base", "open",
            "2999-01-01T00:00:00Z",
        )
        return outcome

    monkeypatch.setattr(review_runner, "analyze_snapshot", analyze_then_push)
    status = execute_review_run(store, run, configured_settings(), fake_fetcher(snap))

    assert status == "superseded"
    assert store.get_findings_for_review_run(run["id"]) == []


def test_inactive_repository_supersedes_the_job(store):
    run = _claimed(store)
    store.set_repository_active(222, is_active=False)
    fetcher = fake_fetcher(snapshot([]))
    assert execute_review_run(store, run, configured_settings(), fetcher) == "superseded"
    assert store.get_review_run(run["id"])["error_code"] == "repository_inactive"
    assert fetcher.calls == []


def test_a_stale_worker_cannot_overwrite_the_current_attempt(store):
    """Worker A claims, stalls past its lease; worker B reclaims and finishes.
    When A finally finishes, its finalize is fenced out and writes nothing."""
    run, _ = enqueue(store)
    t0 = now()
    a = store.claim_next_review_run(60, now=t0)
    b = store.claim_next_review_run(60, now=t0 + timedelta(seconds=120))  # A's lease expired
    assert a["attempts"] == 1 and b["attempts"] == 2

    snap_b = snapshot([changed("src/a.js", head="var unusedB = 1;\n")])
    assert execute_review_run(store, b, configured_settings(), fake_fetcher(snap_b)) == "completed"
    after_b = store.get_review_run(run["id"])
    titles_b = {f["description"] for f in store.get_findings_for_review_run(run["id"])}

    snap_a = snapshot([changed("src/a.js", head="var unusedA = 1;\n")])
    result_a = execute_review_run(store, a, configured_settings(), fake_fetcher(snap_a))

    assert result_a == "fenced_out"
    assert store.get_review_run(run["id"])["attempts"] == after_b["attempts"] == 2
    assert {f["description"] for f in store.get_findings_for_review_run(run["id"])} == titles_b


def test_unexpected_exception_requeues_instead_of_leaving_the_run_running(store, monkeypatch):
    run = _claimed(store)

    def explode(*a, **k):
        raise RuntimeError("boom with secret ghp_abcdefghijklmnopqrstuvwxyz0123456789")

    monkeypatch.setattr(review_runner, "analyze_snapshot", explode)
    snap = snapshot([changed("src/a.js", head="var x = 1;\n")])

    outcome = execute_review_run(store, run, configured_settings(), fake_fetcher(snap))

    assert outcome == "pending"
    stored = store.get_review_run(run["id"])
    assert stored["status"] == "pending" and stored["error_code"] == "internal_error"
    assert "ghp_" not in stored["error_message"]

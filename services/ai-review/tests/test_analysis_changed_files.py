"""The pinned, paginated PR snapshot fetcher (analysis/changed_files.py).

MOCKED HTTP (respx + tests/fake_github.py): no live GitHub App exists in this
environment, so this proves our client logic against expected response shapes.
It is NOT verification against real GitHub — docs/first-deployment-runbook.md
is the path to that.
"""

import httpx
import pytest
import respx

from analysis.changed_files import (
    FILES_PER_PAGE,
    HeadMovedError,
    SnapshotError,
    fetch_pull_request_snapshot,
)
from tests.fake_github import FakeGitHub, entry, file_body, private_key_pem


async def _fetch(gh: FakeGitHub, **kw):
    return await fetch_pull_request_snapshot(
        "12345",
        private_key_pem(),
        gh.installation,
        gh.repo,
        gh.pr,
        expected_head_sha=kw.pop("expected_head_sha", gh.head),
        base_sha=kw.pop("base_sha", gh.base),
        **kw,
    )


def _gh(*entries) -> FakeGitHub:
    gh = FakeGitHub()
    gh.listing = list(entries)
    return gh


# --- happy path & pinning ------------------------------------------------------


@pytest.mark.anyio
async def test_snapshot_pins_every_read_to_an_immutable_sha():
    gh = _gh(
        entry("src/mod.js", "modified", sha="bh1"),
        entry("src/new.js", "added", sha="bh2"),
        entry("src/gone.js", "removed", sha="bh3"),
        entry("src/renamed.js", "renamed", sha="bh4", previous="src/old.js"),
        entry("README.md", "modified"),
        entry(".eslintrc.js", "modified"),
    )
    gh.add_file("src/mod.js", "headsha", "new mod", "bh1")
    gh.add_file("src/mod.js", "mbsha", "old mod")
    gh.add_file("src/new.js", "headsha", "brand new", "bh2")
    gh.add_file("src/gone.js", "mbsha", "deleted code")
    gh.add_file("src/renamed.js", "headsha", "renamed body", "bh4")
    gh.add_file("src/old.js", "mbsha", "renamed body")
    gh.add_file(".eslintrc.json", "basesha", '{"rules": {"no-console": "error"}}')

    with respx.mock as mock:
        gh.mount(mock)
        snap = await _fetch(gh)

    assert (snap.head_sha, snap.base_sha, snap.merge_base_sha) == ("headsha", "basesha", "mbsha")
    by_path = {f.path: f for f in snap.files}
    assert set(by_path) == {"src/mod.js", "src/new.js", "src/gone.js", "src/renamed.js"}
    assert by_path["src/mod.js"].head.content == "new mod"
    assert by_path["src/mod.js"].base.content == "old mod"
    assert by_path["src/new.js"].base is None and by_path["src/new.js"].head is not None
    assert by_path["src/gone.js"].head is None and by_path["src/gone.js"].base is not None
    assert by_path["src/renamed.js"].previous_path == "src/old.js"
    assert snap.rename_map == {"src/old.js": "src/renamed.js"}
    assert snap.trusted_config_text == '{"rules": {"no-console": "error"}}'

    # Nothing was read from "whatever the branch is now": every ref is a pinned SHA.
    assert {ref for _, ref in gh.content_requests} == {"headsha", "mbsha", "basesha"}
    assert ("src/mod.js", "headsha") in gh.content_requests
    assert ("src/mod.js", "mbsha") in gh.content_requests
    assert (".eslintrc.json", "basesha") in gh.content_requests  # trusted config: BASE, not head
    assert (".eslintrc.json", "headsha") not in gh.content_requests
    # Non-analyzable and control files are never even fetched.
    assert not any(p in ("README.md", ".eslintrc.js") for p, _ in gh.content_requests)
    assert {"path": "README.md", "reason": "not_analyzable_type"} in snap.skipped
    assert {"path": ".eslintrc.js", "reason": "not_analyzable_type"} in snap.skipped


@pytest.mark.anyio
async def test_trusted_config_is_read_from_the_base_never_the_pr_head():
    gh = _gh(entry("a.js"))
    gh.add_file("a.js", "headsha", "x")
    gh.add_file("a.js", "mbsha", "y")
    # The PR *adds* a permissive config at head; the base has none.
    gh.add_file(".eslintrc.json", "headsha", '{"rules": {"no-unused-vars": "off"}}')

    with respx.mock as mock:
        gh.mount(mock)
        snap = await _fetch(gh)

    assert snap.trusted_config_text is None


# --- pagination / completeness --------------------------------------------------


@pytest.mark.anyio
async def test_all_pages_are_fetched_never_truncated_at_the_first_page():
    n = FILES_PER_PAGE * 2 + 50  # 250 entries -> 3 pages
    gh = _gh(*[entry(f"src/f{i}.js") for i in range(n)])
    for i in range(n):
        gh.add_file(f"src/f{i}.js", "headsha", "a")
        gh.add_file(f"src/f{i}.js", "mbsha", "b")

    import analysis.changed_files as cf

    original = cf.MAX_FILES
    cf.MAX_FILES = 1000  # this test is about pagination, not the analyzable-file cap
    try:
        with respx.mock as mock:
            gh.mount(mock)
            snap = await _fetch(gh)
    finally:
        cf.MAX_FILES = original

    assert gh.calls.count("files") == 3
    assert len(snap.files) == n and snap.changed_files_total == n


@pytest.mark.anyio
async def test_list_shorter_than_the_reported_count_is_an_error_not_a_partial_result():
    gh = _gh(entry("a.js"))
    gh.changed_files = 5  # GitHub says 5 files changed, but the list has 1
    gh.add_file("a.js", "headsha", "x")
    gh.add_file("a.js", "mbsha", "y")

    with respx.mock as mock:
        gh.mount(mock)
        with pytest.raises(SnapshotError) as exc:
            await _fetch(gh)

    assert exc.value.kind == "file_list_incomplete" and exc.value.retryable is True


@pytest.mark.anyio
async def test_more_analyzable_files_than_the_limit_fails_loudly():
    gh = _gh(*[entry(f"src/f{i}.js") for i in range(201)])
    with respx.mock as mock:
        gh.mount(mock)
        with pytest.raises(SnapshotError) as exc:
            await _fetch(gh)
    assert exc.value.kind == "too_many_files" and exc.value.retryable is False
    # And it stopped before fetching any content.
    assert gh.content_requests == []


@pytest.mark.anyio
async def test_more_files_than_github_can_list_is_not_retryable():
    gh = _gh(entry("a.js"))
    gh.changed_files = 4000
    with respx.mock as mock:
        gh.mount(mock)
        with pytest.raises(SnapshotError) as exc:
            await _fetch(gh)
    assert exc.value.kind == "too_many_files" and not exc.value.retryable


# --- stale heads ---------------------------------------------------------------


@pytest.mark.anyio
async def test_head_already_moved_when_the_run_starts():
    gh = _gh(entry("a.js"))
    gh.head_sequence = ["some-newer-sha"]
    with respx.mock as mock:
        gh.mount(mock)
        with pytest.raises(HeadMovedError) as exc:
            await _fetch(gh)
    assert exc.value.kind == "head_moved" and exc.value.retryable is False
    assert gh.content_requests == []


@pytest.mark.anyio
async def test_head_moving_while_files_are_being_read_is_detected():
    gh = _gh(entry("a.js"))
    gh.add_file("a.js", "headsha", "x")
    gh.add_file("a.js", "mbsha", "y")
    gh.head_sequence = ["headsha", "a-newer-sha"]  # unchanged at start, moved by the end
    with respx.mock as mock:
        gh.mount(mock)
        with pytest.raises(HeadMovedError):
            await _fetch(gh)


# --- per-file outcomes ------------------------------------------------------------


@pytest.mark.anyio
async def test_blob_sha_mismatch_is_recorded_not_trusted():
    gh = _gh(entry("a.js", sha="expected-blob"))
    gh.add_file("a.js", "headsha", "x", sha="different-blob")
    gh.add_file("a.js", "mbsha", "y")
    with respx.mock as mock:
        gh.mount(mock)
        snap = await _fetch(gh)
    assert snap.files[0].head is None
    assert {"path": "a.js", "reason": "blob_mismatch"} in snap.skipped


@pytest.mark.anyio
async def test_symlinks_and_submodules_are_skipped_never_followed():
    gh = _gh(entry("link.js", "added"), entry("sub.js", "added"))
    gh.contents[("link.js", "headsha")] = {**file_body("../../etc/passwd"), "type": "symlink"}
    gh.contents[("sub.js", "headsha")] = {"type": "submodule", "sha": "s"}
    with respx.mock as mock:
        gh.mount(mock)
        snap = await _fetch(gh)
    assert all(f.head is None for f in snap.files)
    assert {e["reason"] for e in snap.skipped} == {"symlink_or_special"}


@pytest.mark.anyio
async def test_binary_and_oversized_content_is_skipped_with_reasons():
    gh = _gh(entry("bin.js", "added"), entry("huge.js", "added"))
    gh.contents[("bin.js", "headsha")] = {
        "type": "file", "encoding": "base64", "size": 3, "sha": "blob1", "content": "//79",
    }  # 0xFF 0xFE 0xFD: not UTF-8
    gh.contents[("huge.js", "headsha")] = {**file_body("x"), "size": 900_000}
    with respx.mock as mock:
        gh.mount(mock)
        snap = await _fetch(gh)
    reasons = {e["path"]: e["reason"] for e in snap.skipped}
    assert reasons == {"bin.js": "binary_or_undecodable", "huge.js": "too_large"}


@pytest.mark.anyio
async def test_unreadable_base_content_is_flagged_so_findings_are_never_called_new():
    gh = _gh(entry("a.js", "modified"))
    gh.add_file("a.js", "headsha", "new")  # no base content -> 404 at the merge base
    with respx.mock as mock:
        gh.mount(mock)
        snap = await _fetch(gh)
    assert snap.files[0].base_unavailable is True and snap.files[0].head is not None
    assert {"path": "a.js", "reason": "base_unavailable"} in snap.skipped


@pytest.mark.anyio
async def test_added_file_has_no_base_and_that_is_not_an_unavailability():
    gh = _gh(entry("a.js", "added"))
    gh.add_file("a.js", "headsha", "new")
    with respx.mock as mock:
        gh.mount(mock)
        snap = await _fetch(gh)
    assert snap.files[0].base is None and snap.files[0].base_unavailable is False
    assert not any(e["reason"] == "base_unavailable" for e in snap.skipped)


@pytest.mark.anyio
async def test_missing_patch_is_preserved_as_none_for_the_local_diff_fallback():
    gh = _gh(entry("a.js", patch=None))
    gh.add_file("a.js", "headsha", "x")
    gh.add_file("a.js", "mbsha", "y")
    with respx.mock as mock:
        gh.mount(mock)
        snap = await _fetch(gh)
    assert snap.files[0].patch is None


@pytest.mark.anyio
async def test_unsafe_paths_from_the_api_are_skipped_and_never_requested():
    gh = _gh(entry("../../etc/passwd.js"), entry("C:/win.js"), entry("ok.js"))
    gh.add_file("ok.js", "headsha", "x")
    gh.add_file("ok.js", "mbsha", "y")
    with respx.mock as mock:
        gh.mount(mock)
        snap = await _fetch(gh)
    assert [f.path for f in snap.files] == ["ok.js"]
    assert {e["reason"] for e in snap.skipped} == {"unsafe_path"}
    assert all(p == "ok.js" or p == ".eslintrc.json" for p, _ in gh.content_requests)


# --- error classification ---------------------------------------------------------


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("status", "headers", "kind", "retryable"),
    [
        (404, {}, "not_found", False),
        (401, {}, "auth", False),
        (403, {}, "auth", False),
        (403, {"x-ratelimit-remaining": "0"}, "rate_limited", True),
        (429, {"retry-after": "42"}, "rate_limited", True),
        (500, {}, "server", True),
        (502, {}, "server", True),
        (422, {}, "unexpected_status", False),
    ],
)
async def test_http_errors_are_classified_as_retryable_or_permanent(status, headers, kind, retryable):
    gh = _gh(entry("a.js"))
    gh.pull_response = httpx.Response(status, headers=headers, json={"message": "x"})
    with respx.mock as mock:
        gh.mount(mock)
        with pytest.raises(SnapshotError) as exc:
            await _fetch(gh)
    assert exc.value.kind == kind and exc.value.retryable is retryable


@pytest.mark.anyio
async def test_retry_after_header_is_surfaced():
    gh = _gh(entry("a.js"))
    gh.pull_response = httpx.Response(429, headers={"retry-after": "42"})
    with respx.mock as mock:
        gh.mount(mock)
        with pytest.raises(SnapshotError) as exc:
            await _fetch(gh)
    assert exc.value.retry_after == 42.0


@pytest.mark.anyio
async def test_network_failure_is_retryable():
    gh = _gh(entry("a.js"))
    gh.pull_exception = httpx.ConnectError("boom")
    with respx.mock as mock:
        gh.mount(mock)
        with pytest.raises(SnapshotError) as exc:
            await _fetch(gh)
    assert exc.value.kind == "network" and exc.value.retryable


@pytest.mark.anyio
@pytest.mark.parametrize(("status", "retryable"), [(500, True), (502, True), (401, False), (404, False)])
async def test_token_mint_failures_are_classified(status, retryable):
    gh = _gh(entry("a.js"))
    gh.token_status = status
    with respx.mock as mock:
        gh.mount(mock)
        with pytest.raises(SnapshotError) as exc:
            await _fetch(gh)
    assert exc.value.kind == "auth" and exc.value.retryable is retryable
    assert "ghs_" not in str(exc.value) and "PRIVATE" not in str(exc.value)


@pytest.mark.anyio
async def test_a_5xx_while_reading_file_content_is_retryable_not_a_silent_skip():
    gh = _gh(entry("a.js"))
    gh.contents[("a.js", "headsha")] = httpx.Response(503, json={"message": "unavailable"})
    gh.add_file("a.js", "mbsha", "y")
    with respx.mock as mock:
        gh.mount(mock)
        with pytest.raises(SnapshotError) as exc:
            await _fetch(gh)
    assert exc.value.retryable and exc.value.kind == "server"

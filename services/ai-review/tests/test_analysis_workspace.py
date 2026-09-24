import pytest

from analysis.workspace import (
    MAX_FILE_SIZE_BYTES,
    MAX_FILES,
    SourceFile,
    WorkspaceLimitError,
    materialize,
)


def test_materialize_writes_files_and_preserves_relative_paths():
    files = [SourceFile(path="src/a.js", content="const a = 1;"), SourceFile(path="b.js", content="const b = 2;")]
    with materialize(files) as workspace:
        assert (workspace / "src" / "a.js").read_text() == "const a = 1;"
        assert (workspace / "b.js").read_text() == "const b = 2;"
        captured_workspace = workspace
    # Cleaned up after the context manager exits, even on success.
    assert not captured_workspace.exists()


def test_materialize_cleans_up_even_when_the_caller_raises():
    files = [SourceFile(path="a.js", content="x")]
    captured = {}
    with pytest.raises(RuntimeError):
        with materialize(files) as workspace:
            captured["path"] = workspace
            raise RuntimeError("simulated analysis failure")
    assert not captured["path"].exists()


def test_materialize_rejects_too_many_files():
    files = [SourceFile(path=f"f{i}.js", content="x") for i in range(MAX_FILES + 1)]
    with pytest.raises(WorkspaceLimitError):
        with materialize(files):
            pass


def test_materialize_rejects_oversized_file():
    files = [SourceFile(path="huge.js", content="x" * (MAX_FILE_SIZE_BYTES + 1))]
    with pytest.raises(WorkspaceLimitError):
        with materialize(files):
            pass


def test_materialize_rejects_path_traversal():
    files = [SourceFile(path="../../etc/passwd", content="x")]
    with pytest.raises(WorkspaceLimitError):
        with materialize(files):
            pass


def test_materialize_rejects_absolute_path():
    files = [SourceFile(path="/etc/passwd", content="x")]
    with pytest.raises(WorkspaceLimitError):
        with materialize(files):
            pass


def test_materialize_handles_empty_file_list():
    with materialize([]) as workspace:
        assert workspace.exists()
        assert list(workspace.iterdir()) == []


# --- Phase 0: path validation, filtering, and skip bookkeeping ---------------

import os  # noqa: E402

from analysis.static_analysis import run_static_analysis  # noqa: E402
from analysis.workspace import (  # noqa: E402
    is_control_file,
    is_incomplete_skip,
    prepare_files,
    unsafe_path_reason,
)


@pytest.mark.parametrize(
    "path",
    ["src/a.js", "a.ts", "deep/er/path/file.tsx", "--dash-leading.js", "with space.js", "ünï.js"],
)
def test_ordinary_paths_are_accepted(path):
    assert unsafe_path_reason(path) is None


@pytest.mark.parametrize(
    "path",
    [
        "", "/abs.js", "../up.js", "a/../b.js", "a/./b.js", "a//b.js", "a\b.js", "C:/x.js",
        "c:x.js", "a.js:stream", "trailing.js ", "trailing.js.", "nul.js", "CON.js",
        "dir/aux.txt.js", "bell\x07.js", "x" * 500 + ".js",
    ],
)
def test_hostile_or_ambiguous_paths_are_rejected(path):
    assert unsafe_path_reason(path) is not None


def test_prepare_files_records_a_reason_for_everything_it_drops():
    files = [
        SourceFile("ok.js", "1"),
        SourceFile("../evil.js", "1"),
        SourceFile(".eslintrc.js", "1"),
        SourceFile("node_modules/pkg/index.js", "1"),
        SourceFile("README.md", "1"),
        SourceFile("ok.js", "duplicate"),
        SourceFile("big.js", "x" * (MAX_FILE_SIZE_BYTES + 1)),
    ]
    prepared = prepare_files(files)

    assert [f.path for f in prepared.files] == ["ok.js"]
    assert {(e["path"], e["reason"]) for e in prepared.skipped} == {
        ("../evil.js", "unsafe_path"),
        (".eslintrc.js", "control_file"),
        ("node_modules/pkg/index.js", "vendored_or_metadata"),
        ("README.md", "not_analyzable_type"),
        ("ok.js", "duplicate_path"),
        ("big.js", "too_large"),
    }


def test_a_file_and_a_path_inside_it_cannot_both_exist():
    prepared = prepare_files([SourceFile("a.js", "1"), SourceFile("a.js/b.js", "2")])
    assert [f.path for f in prepared.files] == ["a.js"]
    assert {"path": "a.js/b.js", "reason": "path_conflict"} in prepared.skipped


def test_only_skips_that_lost_analysis_count_as_incomplete():
    benign = ["control_file", "not_analyzable_type", "vendored_or_metadata", "deleted"]
    lossy = ["unsafe_path", "too_large", "fetch_failed", "base_unavailable", "tool_error", "missing"]
    assert not any(is_incomplete_skip({"path": "x.js", "reason": r}) for r in benign)
    assert all(is_incomplete_skip({"path": "x.js", "reason": r}) for r in lossy)
    # an undecodable .png is nothing to worry about; an undecodable .js is.
    assert not is_incomplete_skip({"path": "logo.png", "reason": "binary_or_undecodable"})
    assert is_incomplete_skip({"path": "app.js", "reason": "binary_or_undecodable"})


@pytest.mark.parametrize(
    "name",
    [".eslintrc", ".eslintrc.cjs", ".ESLINTRC.JSON", "eslint.config.mjs", ".eslintignore",
     ".semgrepignore", "package.json", "package-lock.json", "tsconfig.base.json", ".npmrc"],
)
def test_control_file_detection_is_by_basename_at_any_depth(name):
    assert is_control_file(name) and is_control_file(f"a/b/{name}")


def test_regular_source_files_are_not_control_files():
    assert not any(is_control_file(p) for p in ["src/eslintrc-helper.js", "config.js", "index.ts"])


def test_materialize_writes_bytes_so_line_endings_are_not_rewritten():
    with materialize([SourceFile("a.js", "a\nb\r\nc\n")]) as workspace:
        assert (workspace / "a.js").read_bytes() == b"a\nb\r\nc\n"


def test_cli_never_reads_a_file_outside_the_repository(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (tmp_path / "secret.js").write_text("eval(1);\n")
    (repo / "ok.js").write_text("const a = 1;\nmodule.exports = { a };\n")

    result = run_static_analysis(str(repo), ["../secret.js", "ok.js"])

    assert {"path": "../secret.js", "reason": "unsafe_path"} in result.skipped_files
    assert all(f.file_path != "../secret.js" for f in result.findings)


def test_cli_does_not_follow_a_symlink_out_of_the_repository(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    outside = tmp_path / "outside.js"
    outside.write_text("eval(1);\n")
    try:
        os.symlink(outside, repo / "link.js")
    except (OSError, NotImplementedError):
        pytest.skip("creating symlinks is not permitted in this environment")

    result = run_static_analysis(str(repo), ["link.js"])

    assert {"path": "link.js", "reason": "symlink_or_special"} in result.skipped_files
    assert result.findings == []


def test_total_size_ceiling_is_enforced_across_files():
    from analysis.limits import MAX_TOTAL_BYTES

    per_file = MAX_FILE_SIZE_BYTES - 10
    count = MAX_TOTAL_BYTES // per_file + 2
    assert count <= MAX_FILES
    files = [SourceFile(f"f{i}.js", "x" * per_file) for i in range(count)]
    with pytest.raises(WorkspaceLimitError, match="total size"):
        with materialize(files):
            pass

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

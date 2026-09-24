"""Structural guards for the Phase 0 scope boundary.

Phase 0 is foundation hardening plus deterministic analysis. These tests fail
if the service quietly grows an AI reviewer, an evaluation dependency in
production code, an approving/merging GitHub call, or unrelated products.
They are static (AST/text) checks — they prove absence of the obvious
wiring, not the absence of every possible bypass.
"""

import ast
from pathlib import Path

SERVICE_ROOT = Path(__file__).parent.parent
REPO_ROOT = SERVICE_ROOT.parent.parent
PRODUCTION_DIRS = ("app", "analysis")

AI_SDK_ROOTS = {
    "anthropic", "openai", "google", "vertexai", "cohere", "mistralai", "langchain",
    "langchain_core", "llama_index", "litellm", "transformers", "ollama", "groq",
}


def _production_python_files():
    for d in PRODUCTION_DIRS:
        for path in (SERVICE_ROOT / d).rglob("*.py"):
            if "node_modules" in path.parts or "__pycache__" in path.parts:
                continue
            yield path


def _imported_roots(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    roots = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            roots.add(node.module.split(".")[0])
    return roots


def test_no_ai_provider_sdk_is_imported_anywhere_in_production_code():
    offenders = {
        str(p.relative_to(SERVICE_ROOT)): sorted(_imported_roots(p) & AI_SDK_ROOTS)
        for p in _production_python_files()
        if _imported_roots(p) & AI_SDK_ROOTS
    }
    assert offenders == {}


def test_no_ai_sdk_is_a_declared_dependency():
    for name in ("requirements.txt", "requirements-dev.txt"):
        text = (SERVICE_ROOT / name).read_text(encoding="utf-8").lower()
        for sdk in ("anthropic", "openai", "google-generativeai", "langchain", "litellm"):
            assert sdk not in text, f"{sdk} found in {name}"


def test_no_llm_endpoint_or_prompt_machinery_exists_in_production_code():
    forbidden = (
        "api.anthropic.com", "api.openai.com", "generativelanguage.googleapis.com",
        "messages.create", "chat.completions", "system_prompt", "prompt_builder",
    )
    for path in _production_python_files():
        text = path.read_text(encoding="utf-8").lower()
        for token in forbidden:
            assert token not in text, f"{token!r} in {path.relative_to(SERVICE_ROOT)}"


def test_the_claude_key_setting_is_declared_but_never_read_by_any_module():
    readers = [
        str(p.relative_to(SERVICE_ROOT))
        for p in _production_python_files()
        if "claude_api_key" in p.read_text(encoding="utf-8") and p.name != "config.py"
    ]
    assert readers == []


def test_no_finding_can_be_produced_with_source_ai_by_the_pipeline():
    """Finding.source allows 'AI' for the future schema contract, but nothing
    in Phase 0 code constructs one."""
    for path in _production_python_files():
        if path.name == "finding.py":
            continue
        assert 'source="AI"' not in path.read_text(encoding="utf-8"), path.name


def test_production_code_never_imports_the_evaluation_package():
    for path in _production_python_files():
        roots = _imported_roots(path)
        assert "evaluation" not in roots, f"{path.relative_to(SERVICE_ROOT)} imports evaluation"


def test_evaluation_scaffold_is_documentation_only_in_phase_0():
    evaluation = REPO_ROOT / "evaluation"
    assert (evaluation / "README.md").is_file()
    assert list(evaluation.rglob("*.py")) == []


def test_github_write_surface_is_limited_to_minting_the_installation_token():
    """No comment, review, APPROVE, or merge call exists. Among modules that
    talk HTTP (the only ones that could call GitHub), the sole mutating call is
    the installation-token exchange in app/github_auth.py."""
    hits = []
    for path in _production_python_files():
        text = path.read_text(encoding="utf-8")
        if "httpx" not in _imported_roots(path):
            continue
        for verb in (".post(", ".put(", ".patch(", ".delete("):
            hits.extend((path.name, verb) for _ in range(text.count(verb)))
    assert hits == [("github_auth.py", ".post(")]


def test_no_approve_merge_or_review_submission_strings_in_production_code():
    for path in _production_python_files():
        text = path.read_text(encoding="utf-8")
        for token in ('"APPROVE"', "'APPROVE'", "/merge", "REQUEST_CHANGES", "/reviews"):
            assert token not in text, f"{token} in {path.relative_to(SERVICE_ROOT)}"


def test_no_unrelated_products_have_crept_into_the_repository():
    """CodeArena / coding assessments / judge / trainer are a different product.
    Codentry's boundary is documented in docs/architecture.md."""
    banned = ("codearena", "code-arena", "assessment", "competitive", "trainer", "leaderboard")
    skip_dirs = {"node_modules", ".venv", ".git", "__pycache__", ".next", ".pytest_cache", ".ruff_cache"}
    offenders = []
    for top in ("apps", "services", "packages", "supabase", "evaluation"):
        base = REPO_ROOT / top
        if not base.exists():
            continue
        for path in base.rglob("*"):
            if skip_dirs & set(path.parts) or path.is_dir():
                continue
            if path.name == "test_scope_guards.py":
                continue
            if any(word in path.name.lower() for word in banned):
                offenders.append(str(path.relative_to(REPO_ROOT)))
    assert offenders == []

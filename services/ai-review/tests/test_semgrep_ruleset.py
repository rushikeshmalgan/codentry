"""The production Semgrep ruleset: every rule has a true-positive case and a
false-positive guard, run through the real Semgrep binary. Also asserts the
ruleset stays honestly labeled (small, hand-written, production only)."""

from pathlib import Path

import pytest
import yaml

from analysis.semgrep_runner import RULES_DIR, run_semgrep
from analysis.workspace import SourceFile, materialize

RULES_FILE = RULES_DIR / "production.yml"


def _rule_ids(code: str) -> list[str]:
    with materialize([SourceFile(path="t.js", content=code)]) as workspace:
        result = run_semgrep(workspace, ["t.js"])
    assert result.status == "ok", result.error_message
    return sorted(r["check_id"].rsplit(".", 1)[-1] for r in result.results)


CASES = [
    # (rule id, code that MUST match, code that must NOT match)
    ("hardcoded-secret", 'const apiKey = "sk_live_abcdef1234567890";\n',
     'const apiKey = process.env.API_KEY;\nconst tokenType = "Bearer";\nconst password = "";\n'),
    ("eval-usage", "eval(userInput);\n", "const evaluate = (x) => x;\nevaluate(1);\n"),
    ("new-function-usage", 'const f = new Function("a", "return a");\n',
     "const f = new Foo('a');\n"),
    ("child-process-exec-non-literal", "child_process.exec(cmd);\n",
     'child_process.exec("ls -la");\nchild_process.execFile("ls", [dir]);\n'),
    ("sql-string-concatenation", 'const q = "SELECT * FROM users WHERE id = " + id;\n',
     'const greeting = "hello " + name;\nconst path = "/api/users/" + id;\n'),
    ("innerhtml-assignment", "el.innerHTML = userInput;\n",
     'el.innerHTML = "<b>static</b>";\nel.textContent = userInput;\n'),
]


@pytest.mark.parametrize(("rule", "positive", "negative"), CASES, ids=[c[0] for c in CASES])
def test_rule_detects_the_true_positive(rule, positive, negative):
    assert rule in _rule_ids(positive)


@pytest.mark.parametrize(("rule", "positive", "negative"), CASES, ids=[c[0] for c in CASES])
def test_rule_does_not_fire_on_the_false_positive_guard(rule, positive, negative):
    assert rule not in _rule_ids(negative)


def test_every_rule_in_the_ruleset_has_a_case_in_this_file():
    rules = yaml.safe_load(RULES_FILE.read_text(encoding="utf-8"))["rules"]
    assert {r["id"] for r in rules} == {c[0] for c in CASES}


def test_the_sql_rule_no_longer_matches_arbitrary_string_concatenation():
    """The Phase 3 toy rule (`"..." + $X`) flagged any concatenation."""
    assert _rule_ids('const s = "user-" + id + "-suffix";\n') == []


def test_ruleset_metadata_is_honest_and_complete():
    rules = yaml.safe_load(RULES_FILE.read_text(encoding="utf-8"))["rules"]
    assert len(rules) == 6
    for rule in rules:
        assert rule["metadata"]["category"] == "security"
        assert rule["metadata"]["ruleset"] == "codentry-baseline"
        assert rule["severity"] in {"ERROR", "WARNING", "INFO"}
    readme = (RULES_DIR / "README.md").read_text(encoding="utf-8")
    assert "six hand-written rules" in readme
    assert "not** Semgrep's registry coverage" in readme


def test_only_production_rules_live_in_the_rules_directory():
    """Toy / fixture rules must not sit next to production ones."""
    assert sorted(p.name for p in Path(RULES_DIR).iterdir()) == ["README.md", "production.yml"]


def test_the_ruleset_never_references_the_semgrep_registry():
    text = RULES_FILE.read_text(encoding="utf-8")
    assert "semgrep.dev" not in text and "p/" not in text.replace("pattern", "")

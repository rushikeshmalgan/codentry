"""Unit tests against synthetic raw tool JSON — no subprocess execution here,
that's covered separately in test_analysis_eslint_runner.py /
test_analysis_semgrep_runner.py / test_analysis_static_analysis.py."""

from pathlib import Path

from analysis.normalize import normalize_eslint_result, normalize_semgrep_result

WORKSPACE = Path("/workspace")


def test_normalize_eslint_result_golden():
    raw = {
        "filePath": "/workspace/src/checkout.js",
        "messages": [
            {
                "ruleId": "no-unused-vars",
                "severity": 2,
                "message": "'unusedVar' is assigned a value but never used.",
                "line": 5,
                "column": 9,
                "endLine": 5,
                "endColumn": 18,
            }
        ],
    }

    findings = normalize_eslint_result(raw, WORKSPACE)

    assert len(findings) == 1
    f = findings[0]
    assert f.source == "ESLINT"
    assert f.category == "correctness"
    assert f.severity == "high"
    assert f.confidence is None
    assert f.title == "no-unused-vars"
    assert f.description == "'unusedVar' is assigned a value but never used."
    assert f.file_path == "src/checkout.js"
    assert f.start_line == 5
    assert f.end_line == 5
    assert f.suggestion is None
    assert f.reasoning is None
    assert f.evidence_span is None
    assert len(f.dedup_hash) == 64


def test_normalize_eslint_warning_severity_maps_to_medium():
    raw = {
        "filePath": "/workspace/a.js",
        "messages": [{"ruleId": "no-console", "severity": 1, "message": "Unexpected console.", "line": 1}],
    }
    findings = normalize_eslint_result(raw, WORKSPACE)
    assert findings[0].severity == "medium"


def test_normalize_eslint_missing_end_line_falls_back_to_start_line():
    raw = {
        "filePath": "/workspace/a.js",
        "messages": [{"ruleId": "no-undef", "severity": 2, "message": "x", "line": 7}],
    }
    findings = normalize_eslint_result(raw, WORKSPACE)
    assert findings[0].start_line == 7
    assert findings[0].end_line == 7


def test_normalize_eslint_fatal_parse_error_has_no_rule_id():
    raw = {
        "filePath": "/workspace/broken.js",
        "messages": [{"ruleId": None, "severity": 2, "message": "Parsing error: Unexpected token", "line": 1}],
    }
    findings = normalize_eslint_result(raw, WORKSPACE)
    assert findings[0].title == "eslint-fatal-error"


def test_normalize_eslint_multiple_messages_in_one_file():
    raw = {
        "filePath": "/workspace/a.js",
        "messages": [
            {"ruleId": "no-unused-vars", "severity": 2, "message": "a", "line": 1},
            {"ruleId": "no-undef", "severity": 2, "message": "b", "line": 2},
        ],
    }
    findings = normalize_eslint_result(raw, WORKSPACE)
    assert len(findings) == 2
    assert findings[0].dedup_hash != findings[1].dedup_hash


def test_normalize_semgrep_result_golden():
    raw = {
        "check_id": "analysis.semgrep-rules.eval-usage",
        "path": "/workspace/src/run.js",
        "start": {"line": 4, "col": 10},
        "end": {"line": 4, "col": 25},
        "extra": {
            "message": "eval() executes a string as code.",
            "severity": "ERROR",
            "metadata": {"category": "security"},
        },
    }

    f = normalize_semgrep_result(raw, WORKSPACE)

    assert f.source == "SEMGREP"
    assert f.category == "security"
    assert f.severity == "high"
    assert f.confidence is None
    assert f.title == "eval-usage"
    assert f.description == "eval() executes a string as code."
    assert f.file_path == "src/run.js"
    assert f.start_line == 4
    assert f.end_line == 4
    assert len(f.dedup_hash) == 64


def test_normalize_semgrep_severity_mapping():
    def make(severity):
        return {
            "check_id": "x.rule",
            "path": "/workspace/a.js",
            "start": {"line": 1},
            "end": {"line": 1},
            "extra": {"message": "m", "severity": severity, "metadata": {}},
        }

    assert normalize_semgrep_result(make("ERROR"), WORKSPACE).severity == "high"
    assert normalize_semgrep_result(make("WARNING"), WORKSPACE).severity == "medium"
    assert normalize_semgrep_result(make("INFO"), WORKSPACE).severity == "low"


def test_normalize_semgrep_unknown_category_falls_back_to_security():
    raw = {
        "check_id": "x.rule",
        "path": "/workspace/a.js",
        "start": {"line": 1},
        "end": {"line": 1},
        "extra": {"message": "m", "severity": "ERROR", "metadata": {"category": "not-a-real-category"}},
    }
    assert normalize_semgrep_result(raw, WORKSPACE).category == "security"


def test_normalize_semgrep_rule_id_strips_config_path_prefix():
    raw = {
        "check_id": "some.long.config.path.prefix.hardcoded-secret",
        "path": "/workspace/a.js",
        "start": {"line": 1},
        "end": {"line": 1},
        "extra": {"message": "m", "severity": "ERROR", "metadata": {}},
    }
    assert normalize_semgrep_result(raw, WORKSPACE).title == "hardcoded-secret"

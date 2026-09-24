"""The ESLint configuration trust boundary."""

import json

from analysis.trusted_config import (
    TRUSTED_CONFIG_FILENAME,
    build_effective_config,
    sanitize_overlay,
    write_effective_config,
)


def test_overlay_keeps_only_rules_env_and_globals():
    overlay = sanitize_overlay(
        json.dumps(
            {
                "root": True,
                "parser": "./evil-parser.js",
                "plugins": ["evil"],
                "extends": ["./evil.js"],
                "processor": "evil/x",
                "overrides": [{"files": ["*"], "rules": {}}],
                "parserOptions": {"project": "./tsconfig.json"},
                "settings": {},
                "rules": {"no-console": "error"},
                "env": {"node": True},
                "globals": {"MY_GLOBAL": "readonly"},
            }
        )
    )
    assert overlay.rules == {"no-console": "error"}
    assert overlay.env == {"node": True}
    assert overlay.globals == {"MY_GLOBAL": "readonly"}
    for key in ("parser", "plugins", "extends", "processor", "overrides", "parserOptions"):
        assert f"key:{key}" in overlay.dropped

    effective = build_effective_config(overlay)
    for forbidden in ("plugins", "processor"):
        assert forbidden not in effective
    assert "./evil" not in json.dumps(effective)


def test_overlay_rejects_plugin_rules_bad_severities_and_weird_names():
    overlay = sanitize_overlay(
        json.dumps(
            {
                "rules": {
                    "evil-plugin/some-rule": "error",  # third-party plugin rule
                    "no-console": "banana",  # not a severity
                    "../../x": "error",
                    "no-debugger": ["error"],
                    "@typescript-eslint/no-explicit-any": "warn",
                    "eqeqeq": [2, "always"],
                }
            }
        )
    )
    assert set(overlay.rules) == {"no-debugger", "@typescript-eslint/no-explicit-any", "eqeqeq"}
    assert any(d.startswith("rule:evil-plugin") for d in overlay.dropped)


def test_overlay_rejects_unknown_envs_and_bad_globals():
    overlay = sanitize_overlay(
        json.dumps(
            {
                "env": {"node": True, "some-plugin/env": True, "browser": "yes"},
                "globals": {"OK": "readonly", "bad name": "readonly", "X": "banana"},
            }
        )
    )
    assert overlay.env == {"node": True}
    assert overlay.globals == {"OK": "readonly"}


def test_hostile_or_garbled_input_yields_an_empty_overlay_never_an_exception():
    for text in ("{not json", "[]", '"a string"', "null", "x" * 200_000, "{" * 5000):
        overlay = sanitize_overlay(text)
        assert overlay.is_empty
        assert overlay.dropped


def test_effective_config_is_baseline_when_there_is_no_overlay():
    config = build_effective_config(None)
    assert config["root"] is True
    assert "eslint:recommended" in config["extends"]


def test_effective_config_rewrites_the_ts_parser_to_an_absolute_pinned_path():
    config = build_effective_config(None)
    parsers = [o["parser"] for o in config["overrides"] if "parser" in o]
    assert parsers
    for parser in parsers:
        assert "node_modules" in parser and "eslint-baseline" in parser
        assert parser != "@typescript-eslint/parser"


def test_overlay_can_change_rules_but_cannot_remove_baseline_structure():
    overlay = sanitize_overlay('{"rules": {"no-unused-vars": "off"}}')
    config = build_effective_config(overlay)
    assert config["rules"]["no-unused-vars"] == "off"  # trusted-branch policy choice
    assert config["root"] is True and config["extends"]


def test_generated_config_is_written_outside_the_workspace(tmp_path):
    path = write_effective_config(tmp_path, None)
    assert path.parent == tmp_path
    assert json.loads(path.read_text("utf-8"))["root"] is True


def test_only_the_json_config_filename_is_ever_read_from_the_base_commit():
    assert TRUSTED_CONFIG_FILENAME == ".eslintrc.json"

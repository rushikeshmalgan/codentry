"""The ESLint configuration trust boundary.

Nothing that arrives with the pull request under review may configure the
tools that review it. ESLint config is *code*: `.eslintrc.js` is executed,
and `parser`, `extends`, `plugins`, and `processor` all `require()` files
resolved relative to the config — so honoring a PR-supplied config was a
remote-code-execution primitive (verified by tests/test_security_poc.py
against the Phase 3 code) as well as a way for a PR to disable its own
review.

The effective configuration is therefore:

    Codentry's pinned baseline  (analysis/eslint-baseline/.eslintrc.baseline.json)
      +  an OPTIONAL sanitized overlay read from `.eslintrc.json` at the
         trusted BASE commit (never the PR head)

The overlay may contribute only `rules`, `env`, and `globals`, and each is
validated. `parser`, `plugins`, `extends`, `processor`, `overrides`,
`settings`, `parserOptions`, and every JavaScript/YAML config format are
dropped. The generated file lives in a sandbox directory outside the
analysis workspace.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from analysis.limits import MAX_TRUSTED_CONFIG_BYTES, MAX_TRUSTED_CONFIG_RULES

BASELINE_DIR = Path(__file__).parent / "eslint-baseline"
BASELINE_CONFIG_PATH = BASELINE_DIR / ".eslintrc.baseline.json"
_TS_PARSER_PATH = BASELINE_DIR / "node_modules" / "@typescript-eslint" / "parser"

# The only file, at the trusted base commit, that may contribute an overlay.
TRUSTED_CONFIG_FILENAME = ".eslintrc.json"

_RULE_NAME = re.compile(r"^(?:@typescript-eslint/)?[a-z0-9][a-z0-9\-]*$")
_GLOBAL_NAME = re.compile(r"^[A-Za-z_$][\w$]*$")
_SEVERITIES = {"off", "warn", "error", 0, 1, 2}
_GLOBAL_VALUES = {"readonly", "readable", "writable", "writeable", "off", True, False}
# Built-in environments only; anything plugin-provided contains a "/".
_ENV_NAMES = frozenset(
    {"browser", "node", "commonjs", "shared-node-browser", "es6", "es2015", "es2016",
     "es2017", "es2018", "es2019", "es2020", "es2021", "es2022", "es2023", "worker",
     "serviceworker", "webextensions", "jest", "mocha", "jasmine", "jquery"}
)


@dataclass(frozen=True)
class TrustedOverlay:
    rules: dict[str, Any] = field(default_factory=dict)
    env: dict[str, bool] = field(default_factory=dict)
    globals: dict[str, Any] = field(default_factory=dict)
    source_ref: str | None = None
    sha256: str | None = None
    dropped: tuple[str, ...] = ()

    @property
    def is_empty(self) -> bool:
        return not (self.rules or self.env or self.globals)


def _valid_rule_config(value: Any) -> bool:
    if isinstance(value, list):
        return bool(value) and value[0] in _SEVERITIES
    return value in _SEVERITIES


def sanitize_overlay(text: str, source_ref: str | None = None) -> TrustedOverlay:
    """Parses and sanitizes a base-commit `.eslintrc.json`.

    Never raises on hostile/garbled input: unparseable or oversized content
    yields an empty overlay (baseline only) with the reason in `dropped`.
    Strict JSON only — no comments, no JS.
    """
    if len(text.encode("utf-8", errors="replace")) > MAX_TRUSTED_CONFIG_BYTES:
        return TrustedOverlay(source_ref=source_ref, dropped=("config_too_large",))
    try:
        parsed = json.loads(text)
    except (json.JSONDecodeError, RecursionError):
        return TrustedOverlay(source_ref=source_ref, dropped=("config_not_valid_json",))
    if not isinstance(parsed, dict):
        return TrustedOverlay(source_ref=source_ref, dropped=("config_not_an_object",))

    dropped: list[str] = [
        f"key:{key}" for key in parsed if key not in ("rules", "env", "globals", "root")
    ]

    rules: dict[str, Any] = {}
    raw_rules = parsed.get("rules")
    if isinstance(raw_rules, dict):
        for name, value in raw_rules.items():
            if len(rules) >= MAX_TRUSTED_CONFIG_RULES:
                dropped.append("rules:truncated")
                break
            if isinstance(name, str) and _RULE_NAME.match(name) and _valid_rule_config(value):
                rules[name] = value
            else:
                dropped.append(f"rule:{str(name)[:60]}")

    env: dict[str, bool] = {}
    raw_env = parsed.get("env")
    if isinstance(raw_env, dict):
        for name, value in raw_env.items():
            if name in _ENV_NAMES and isinstance(value, bool):
                env[name] = value
            else:
                dropped.append(f"env:{str(name)[:60]}")

    globals_: dict[str, Any] = {}
    raw_globals = parsed.get("globals")
    if isinstance(raw_globals, dict):
        for name, value in raw_globals.items():
            if isinstance(name, str) and _GLOBAL_NAME.match(name) and value in _GLOBAL_VALUES:
                globals_[name] = value
            else:
                dropped.append(f"global:{str(name)[:60]}")

    return TrustedOverlay(
        rules=rules,
        env=env,
        globals=globals_,
        source_ref=source_ref,
        sha256=hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest(),
        dropped=tuple(dropped),
    )


def build_effective_config(overlay: TrustedOverlay | None = None) -> dict[str, Any]:
    """Baseline config with the overlay merged on top.

    The baseline's per-language `parser` entries are rewritten to absolute
    paths inside Codentry's own pinned install, because the generated file is
    written outside that directory and ESLint resolves a bare parser name
    relative to the config file's location.
    """
    config: dict[str, Any] = copy.deepcopy(json.loads(BASELINE_CONFIG_PATH.read_text("utf-8")))
    for override in config.get("overrides", []):
        if override.get("parser") == "@typescript-eslint/parser":
            override["parser"] = str(_TS_PARSER_PATH)

    if overlay is not None:
        config["env"] = {**config.get("env", {}), **overlay.env}
        config["globals"] = {**config.get("globals", {}), **overlay.globals}
        config["rules"] = {**config.get("rules", {}), **overlay.rules}
    return config


def write_effective_config(dest_dir: Path, overlay: TrustedOverlay | None = None) -> Path:
    path = dest_dir / "eslintrc.effective.json"
    path.write_text(json.dumps(build_effective_config(overlay), indent=2), encoding="utf-8")
    return path


def baseline_config_sha256() -> str:
    return hashlib.sha256(BASELINE_CONFIG_PATH.read_bytes()).hexdigest()

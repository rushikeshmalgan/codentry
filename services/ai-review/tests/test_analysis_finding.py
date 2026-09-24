"""Finding model contract. Identity behavior lives in tests/test_identity.py."""

import pytest
from pydantic import ValidationError

from analysis.finding import Finding


def _finding(**overrides):
    base = dict(
        source="ESLINT",
        category="correctness",
        severity="high",
        title="no-undef",
        description="'x' is not defined.",
        file_path="a.js",
        start_line=1,
        end_line=1,
    )
    base.update(overrides)
    return Finding(**base)


def test_finding_rejects_invalid_category():
    with pytest.raises(ValidationError):
        _finding(category="not-a-real-category")


def test_finding_static_source_has_null_confidence_reasoning_evidence():
    f = _finding()
    assert f.confidence is None
    assert f.reasoning is None
    assert f.evidence_span is None
    assert f.suggestion is None


def test_finding_differential_fields_default_to_unclassified():
    """A finding not produced by the differential step must not claim to be new."""
    f = _finding()
    assert f.change_status is None
    assert f.moved is False
    assert f.in_diff is False
    assert f.base_start_line is None
    assert f.identity_key is None


def test_finding_rejects_invalid_change_status():
    with pytest.raises(ValidationError):
        _finding(change_status="brand-new")

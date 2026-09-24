from analysis.finding import Finding, compute_dedup_hash


def test_dedup_hash_is_deterministic():
    h1 = compute_dedup_hash("ESLINT", "src/a.js", 3, 3, "no-unused-vars")
    h2 = compute_dedup_hash("ESLINT", "src/a.js", 3, 3, "no-unused-vars")
    assert h1 == h2


def test_dedup_hash_differs_on_any_stable_field_change():
    base = compute_dedup_hash("ESLINT", "src/a.js", 3, 3, "no-unused-vars")
    assert compute_dedup_hash("SEMGREP", "src/a.js", 3, 3, "no-unused-vars") != base
    assert compute_dedup_hash("ESLINT", "src/b.js", 3, 3, "no-unused-vars") != base
    assert compute_dedup_hash("ESLINT", "src/a.js", 4, 4, "no-unused-vars") != base
    assert compute_dedup_hash("ESLINT", "src/a.js", 3, 3, "no-undef") != base


def test_dedup_hash_excludes_message_text_and_timestamps():
    """The hash is computed only from (source, file_path, start_line, end_line,
    rule_id) — nothing time-based or message-text-based feeds it, so the
    same underlying issue hashes identically even if the tool's wording
    changes between versions."""
    h1 = compute_dedup_hash("ESLINT", "src/a.js", 3, 3, "no-unused-vars")
    h2 = compute_dedup_hash("ESLINT", "src/a.js", 3, 3, "no-unused-vars")
    assert h1 == h2
    assert len(h1) == 64  # sha256 hexdigest length, sanity check it's a real hash


def test_finding_rejects_invalid_category():
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        Finding(
            source="ESLINT",
            category="not-a-real-category",
            severity="high",
            title="x",
            description="x",
            file_path="a.js",
            start_line=1,
            end_line=1,
            dedup_hash="x",
        )


def test_finding_static_source_has_null_confidence_reasoning_evidence():
    f = Finding(
        source="ESLINT",
        category="correctness",
        severity="high",
        title="no-undef",
        description="'x' is not defined.",
        file_path="a.js",
        start_line=1,
        end_line=1,
        dedup_hash=compute_dedup_hash("ESLINT", "a.js", 1, 1, "no-undef"),
    )
    assert f.confidence is None
    assert f.reasoning is None
    assert f.evidence_span is None
    assert f.suggestion is None

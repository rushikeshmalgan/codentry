"""The programmatic license check the importers rely on. A check that only ever says
yes would be worthless, so most of these tests are inputs it must refuse."""

import pytest

from evaluation.datasets.licensing import classify, verify
from evaluation.tests.helpers import REPO_ROOT

LICENSES = REPO_ROOT / "evaluation" / "datasets" / "licenses"


def text(name: str) -> str:
    return (LICENSES / name).read_bytes().decode("utf-8")


def test_the_standard_texts_are_recognized():
    assert classify(text("validator.LICENSE")) == "MIT"
    assert classify(text("semver.LICENSE")) == "ISC"
    assert classify(text("bugsjs-shields.LICENSE")) == "CC0-1.0"


def test_mit_is_recognized_whatever_the_title_copyright_line_or_quote_style():
    """Express's text differs from the others only in quote style; titles and copyright
    lines always differ."""
    assert classify(text("bugsjs-express.LICENSE")) == "MIT"
    assert classify("Anyone 1999\n\n" + text("validator.LICENSE")[text("validator.LICENSE").index("Permission"):]) == "MIT"


def test_a_changed_mit_body_is_not_accepted():
    original = text("validator.LICENSE")
    weakened = original.replace("WITHOUT WARRANTY OF ANY KIND", "WITH A WARRANTY OF SOME KIND")
    assert weakened != original and classify(weakened) is None
    assert classify(original.replace("without limitation", "with some limitation")) is None
    truncated = original[: original.index("THE SOFTWARE IS PROVIDED")]
    assert classify(truncated) is None  # a grant with no disclaimer is not the MIT license


def test_other_or_missing_licenses_are_refused():
    for other in (
        "",
        "All rights reserved.",
        "Licensed under the Apache License, Version 2.0 (the License)",
        "GNU GENERAL PUBLIC LICENSE Version 3, 29 June 2007",
        "Permission is hereby granted to use this only for non-commercial purposes.",
    ):
        assert classify(other) is None, other


def test_verify_returns_a_sentence_for_the_manifest_and_names_the_license_kind():
    sentence = verify(text("semver.LICENSE"), "ISC")
    assert "ISC" in sentence and "machine" in sentence
    assert "CC0" in verify(text("bugsjs-shields.LICENSE"), "CC0-1.0")


@pytest.mark.parametrize(
    "file, declared",
    [("validator.LICENSE", "ISC"), ("semver.LICENSE", "MIT"), ("validator.LICENSE", "CC0-1.0")],
)
def test_verify_refuses_a_license_that_is_not_the_declared_one(file, declared):
    with pytest.raises(ValueError, match="classifies as"):
        verify(text(file), declared)

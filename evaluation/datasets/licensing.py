"""Programmatic license checks for redistributed third-party code.

Every importer records *how* it verified a license, not just that someone did. The
checks are deliberately narrow: they recognize exactly the licenses this corpus
accepts (MIT, ISC and CC0-1.0) and refuse anything else, so an unexpected license
stops an import instead of slipping into the repository.

They read the license TEXT, not GitHub's label: a label can be wrong or missing
(lodash's license, for instance, is reported as NOASSERTION).
"""

from __future__ import annotations

import hashlib

# SHA-256 of the MIT permission grant and warranty disclaimer ("Permission is hereby
# granted ..." to the end), whitespace-normalized and with ' read as ". Identical across
# all fifteen MIT projects in this corpus; the copyright line and title are not compared.
MIT_BODY_SHA256 = "fe2a9817987f862eaced948f0468c7f51d2fedfc48c5c505b246a49a3870e9a5"

# The ISC permission grant and warranty disclaimer, whitespace-normalized.
ISC_BODY_SHA256 = "4829cc8e654be69dd1edcebedbda21758a239c230e38f532d6bf4b0adc1a0427"


def _normalized_body(text: str, marker: str) -> str | None:
    if marker not in text:
        return None
    return " ".join(text[text.index(marker) :].split()).replace("'", '"')


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def classify(text: str) -> str | None:
    """'MIT', 'ISC', 'CC0-1.0', or None if the text is none of the accepted licenses."""
    mit = _normalized_body(text, "Permission is hereby granted")
    if mit is not None and _sha256(mit) == MIT_BODY_SHA256:
        return "MIT"
    isc = _normalized_body(text, "Permission to use, copy, modify")
    if isc is not None and _sha256(isc) == ISC_BODY_SHA256:
        return "ISC"
    normalized = " ".join(text.split())
    if "CC0 UNIVERSAL" in normalized.upper() and "Statement of Purpose" in normalized:
        return "CC0-1.0"
    return None


def verify(text: str, declared: str) -> str:
    """The sentence to record in a manifest; raises if the text is not the declared license."""
    found = classify(text)
    if found != declared:
        raise ValueError(f"license text classifies as {found!r}, expected {declared!r}")
    how = {
        "MIT": "the permission grant and warranty disclaimer are identical to the standard MIT "
        "text after whitespace normalization",
        "ISC": "the permission grant and warranty disclaimer are identical to the standard ISC "
        "text after whitespace normalization",
        "CC0-1.0": "the text is the CC0 1.0 Universal public-domain dedication "
        "(Statement of Purpose "
        "present)",
    }[found]
    return (
        f"license text read by machine on import: {how}. "
        "Redistribution is permitted; see ../THIRD_PARTY_NOTICES.md."
    )

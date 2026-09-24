"""Best-effort secret redaction for anything derived from repository content
that is about to be stored, logged, or (from Phase 5) posted to a PR.

Tool error snippets can quote source lines (a parse error prints the
offending token), and a finding message can echo an identifier or literal.
If a contributor committed a credential, Codentry must not copy it into its
own database or into a public PR comment.

This is deliberately pattern-based and conservative — it catches well-known
credential formats and `secret = "..."` assignments. It is NOT a guarantee
that no secret can survive (a bespoke token format will pass through), and
docs/architecture.md says so.
"""

from __future__ import annotations

import re

REDACTED = "[REDACTED]"

_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(
        r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?(?:-----END [A-Z ]*PRIVATE KEY-----|$)", re.S
    ),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"),
    re.compile(r"\bsk-ant-[A-Za-z0-9_\-]{20,}\b"),
    re.compile(r"\bsk-[A-Za-z0-9_\-]{24,}\b"),
    re.compile(r"\bxox[abprs]-[A-Za-z0-9\-]{10,}\b"),
    re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"),
    re.compile(r"\bAIza[0-9A-Za-z_\-]{30,}\b"),
    re.compile(r"\beyJ[A-Za-z0-9_\-]{8,}\.eyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\b"),
    re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._\-]{20,}"),
    # url with embedded credentials: scheme://user:pass@host
    re.compile(r"(?i)\b([a-z][a-z0-9+.\-]*://)[^\s/:@]+:[^\s/@]+@"),
)

# key = "value" / key: 'value' where the key looks like a credential name.
_ASSIGNMENT = re.compile(
    r"""(?ix)
    \b([\w.\-]*(?:secret|passw(?:or)?d|passwd|api[_\-]?key|access[_\-]?key|
        private[_\-]?key|auth[_\-]?token|token|credential)[\w.\-]*)
    (\s*[:=]\s*)
    (["'`])([^"'`\r\n]{6,})\3
    """
)


def redact_secrets(text: str | None) -> str | None:
    """Returns `text` with recognizable credentials masked. None passes through."""
    if not text:
        return text

    redacted = text
    for pattern in _PATTERNS:
        if pattern.groups:
            redacted = pattern.sub(lambda m: f"{m.group(1)}{REDACTED}@", redacted)
        else:
            redacted = pattern.sub(REDACTED, redacted)

    redacted = _ASSIGNMENT.sub(
        lambda m: f"{m.group(1)}{m.group(2)}{m.group(3)}{REDACTED}{m.group(3)}", redacted
    )
    return redacted


def truncate_and_redact(text: str | None, limit: int = 300) -> str:
    """For tool stderr/stdout snippets that end up in error messages."""
    # Redact BEFORE truncating: cutting first could slice a credential in
    # half and leave a recognizable-but-unmatched prefix in the output.
    return (redact_secrets((text or "")[:10_000]) or "")[:limit].strip()

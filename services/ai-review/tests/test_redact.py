"""Secret redaction for text derived from repository content."""

import pytest

from analysis.redact import REDACTED, redact_secrets, truncate_and_redact


@pytest.mark.parametrize(
    "secret",
    [
        "ghp_abcdefghijklmnopqrstuvwxyz0123456789",
        "github_pat_11ABCDEFG0123456789_abcdefghijklmnopqrstuvwxyz",
        "sk-ant-api03-abcdefghijklmnopqrstuvwxyz0123456789",
        "sk-abcdefghijklmnopqrstuvwxyz012345",
        "xoxb-1234567890-abcdefghij",
        "AKIAABCDEFGHIJKLMNOP",
        "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.abcdefghijklmnop",
        "Bearer abcdefghijklmnopqrstuvwxyz012345",
    ],
)
def test_well_known_credential_formats_are_masked(secret):
    text = f"unexpected token near {secret} at position 3"
    out = redact_secrets(text)
    assert secret not in out
    assert REDACTED in out


def test_private_key_blocks_are_masked_including_truncated_ones():
    block = "-----BEGIN RSA PRIVATE KEY-----\nMIIEow...\n-----END RSA PRIVATE KEY-----"
    assert "MIIEow" not in redact_secrets(f"parse error in {block}")
    assert "MIIEow" not in redact_secrets("-----BEGIN PRIVATE KEY-----\nMIIEow...")


def test_credential_assignments_are_masked_but_keep_the_variable_name():
    out = redact_secrets('const apiKey = "sk_live_abcdef1234567890"; password: \'hunter2hunter2\'')
    assert "abcdef1234567890" not in out
    assert "hunter2hunter2" not in out
    assert "apiKey" in out and "password" in out


def test_urls_with_embedded_credentials_are_masked():
    out = redact_secrets("failed to connect to postgres://admin:s3cretpass@db.internal:5432/app")
    assert "s3cretpass" not in out
    assert "db.internal" in out


def test_ordinary_text_is_untouched():
    text = "'unusedVar' is assigned a value but never used. See line 12."
    assert redact_secrets(text) == text


def test_none_and_empty_pass_through():
    assert redact_secrets(None) is None
    assert redact_secrets("") == ""


def test_truncation_happens_after_redaction_so_a_secret_is_never_sliced():
    secret = "ghp_abcdefghijklmnopqrstuvwxyz0123456789"
    text = "x" * 284 + " " + secret  # the secret straddles the 300-char cut
    out = truncate_and_redact(text, limit=300)
    assert "ghp_" not in out
    assert len(out) <= 300

"""Every table the migrations create has row level security enabled.

Migration 0005 closed the Supabase Data API to the anon key by enabling RLS on all six
tables (docs/architecture.md gap #10). A later migration that creates a table and forgets
`enable row level security` would silently reopen the API for that table, so this static
check reads supabase/migrations/*.sql and fails if any created table never gets RLS.

It reads the repository's top-level supabase/ directory, which is outside the Docker
image's build context; there it is skipped (the ai-review CI job runs it on the checkout).
"""

import re
from pathlib import Path

import pytest

MIGRATIONS = Path(__file__).parent.parent.parent.parent / "supabase" / "migrations"

_COMMENT = re.compile(r"--[^\n]*")
_CREATE = re.compile(
    r"\bcreate\s+table\s+(?:if\s+not\s+exists\s+)?(?:public\.)?\"?(\w+)\"?", re.IGNORECASE
)
_ENABLE_RLS = re.compile(
    r"\balter\s+table\s+(?:if\s+exists\s+)?(?:only\s+)?(?:public\.)?\"?(\w+)\"?\s+"
    r"enable\s+row\s+level\s+security",
    re.IGNORECASE,
)


def _sql() -> str:
    if not MIGRATIONS.is_dir():
        pytest.skip("supabase/migrations is not available here (e.g. inside the Docker image)")
    files = sorted(MIGRATIONS.glob("*.sql"))
    assert files, "no migrations found; this check would pass vacuously"
    return "\n".join(_COMMENT.sub("", f.read_text(encoding="utf-8")) for f in files)


def test_every_created_table_has_row_level_security_enabled():
    sql = _sql()
    created = set(_CREATE.findall(sql))
    secured = set(_ENABLE_RLS.findall(sql))
    assert {"installations", "webhook_deliveries", "findings"} <= created  # the parser works
    assert created - secured == set(), (
        "tables without `alter table ... enable row level security` in any migration"
    )


def test_the_check_recognizes_a_table_without_rls():
    """The guard itself: a table created without RLS is reported."""
    sql = "create table if not exists inbox (id uuid);\n-- alter table inbox enable row level security;"
    stripped = _COMMENT.sub("", sql)
    assert set(_CREATE.findall(stripped)) - set(_ENABLE_RLS.findall(stripped)) == {"inbox"}

"""Standalone static-analysis pipeline: changed files -> ESLint + Semgrep ->
normalized Finding[]. Zero imports from `app.*`, zero AI/GitHub/Supabase
calls anywhere in this package — see analysis/run.py and
docs/static-analysis.md for how that's verified, not just claimed.

The one exception, by design, is `analysis.changed_files`, which fetches PR
content from GitHub and therefore does depend on `app.github_auth` (reusing
Phase 2's auth rather than inventing a second one, per spec). Nothing else
in this package imports it, and the standalone CLI (`analysis.run`) never
does either.
"""

#!/usr/bin/env python3
"""Track G checklist: check ONE real pull request end to end, after the GitHub App exists.

Run it once after following docs/first-deployment-runbook.md (procedure:
docs/track-g-checklist.md). It answers, with observed values:

  - does Render answer /health, is the review worker running, and how long does a cold
    start take (vs. the Vercel forward budget and GitHub's 10 s webhook timeout)?
  - does Vercel report the backend reachable, and is the webhook route live?
  - did the pull request reach Supabase: repository, pull request, webhook deliveries?
  - did exactly one review run per head commit happen, and how did it end?
  - which findings were stored, by change status?
  - after a GitHub "Redeliver": was the redelivery deduplicated (no second job)?
  - is the Supabase Data API closed to the anon key (migration 0005; architecture.md gap #10)?

Read-only: it only sends GET requests. Credentials come from environment variables and
are never printed or written: SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY, and optionally
SUPABASE_ANON_KEY; RENDER_URL and VERCEL_URL can be flags or environment variables.
Standard library only, so it runs without the service's virtualenv.

Exit status: 0 if no check FAILED, 1 otherwise, 2 on a usage error.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

GITHUB_WEBHOOK_TIMEOUT_S = 10.0
# apps/web/lib/internal-client.ts: a 4000 ms forward, 300 ms pause, one 4000 ms retry.
VERCEL_FORWARD_BUDGET_S = 8.3
# app/store.py DELIVERY_LEASE_SECONDS: a `processing` delivery older than this is stuck.
DELIVERY_LEASE_S = 120
TERMINAL_OK = ("completed", "partial")
IN_FLIGHT = ("pending", "running")

PASS, FAIL, INFO, SKIP = "PASS", "FAIL", "INFO", "SKIP"


@dataclass(frozen=True)
class Response:
    status: int  # 0 = no HTTP response (DNS, refused, timeout)
    body: bytes
    seconds: float

    def json(self):
        try:
            return json.loads(self.body.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            return None


@dataclass(frozen=True)
class Check:
    name: str
    status: str
    observed: str
    expected: str


Fetch = Callable[[str, dict[str, str]], Response]


def http_get(url: str, headers: dict[str, str], timeout: float = 90.0) -> Response:
    request = urllib.request.Request(url, headers=headers, method="GET")
    start = time.monotonic()
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return Response(response.status, response.read(), time.monotonic() - start)
    except urllib.error.HTTPError as exc:
        return Response(exc.code, exc.read(), time.monotonic() - start)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return Response(0, type(exc).__name__.encode(), time.monotonic() - start)


def _short(value: object, limit: int = 160) -> str:
    text = str(value)
    return text if len(text) <= limit else text[: limit - 1] + "…"


class TrackG:
    def __init__(
        self,
        fetch: Fetch,
        *,
        supabase_url: str | None,
        service_key: str | None,
        anon_key: str | None,
        render_url: str | None,
        vercel_url: str | None,
        now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        self._fetch = fetch
        self._supabase_url = supabase_url.rstrip("/") if supabase_url else None
        self._service_key = service_key
        self._anon_key = anon_key
        self._render_url = render_url.rstrip("/") if render_url else None
        self._vercel_url = vercel_url.rstrip("/") if vercel_url else None
        self._now = now

    # --- HTTP helpers -------------------------------------------------------------
    def _rest(self, table: str, params: dict[str, str], key: str | None = None) -> Response:
        key = key or self._service_key or ""
        query = urllib.parse.urlencode(params, safe=",.()*:")
        return self._fetch(
            f"{self._supabase_url}/rest/v1/{table}?{query}",
            {"apikey": key, "Authorization": f"Bearer {key}"},
        )

    def _rows(self, table: str, params: dict[str, str]) -> list[dict] | None:
        response = self._rest(table, params)
        rows = response.json() if response.status == 200 else None
        return rows if isinstance(rows, list) else None

    # --- Render -------------------------------------------------------------------
    def render_checks(self, cold_start: bool) -> list[Check]:
        if not self._render_url:
            return [Check("render_health", SKIP, "no --render-url / RENDER_URL", "")]
        response = self._fetch(f"{self._render_url}/health", {})
        body = response.json() if response.status == 200 else None
        ok = isinstance(body, dict) and body.get("status") == "ok"
        checks = [
            Check(
                "render_health",
                PASS if ok else FAIL,
                f"HTTP {response.status} in {response.seconds:.1f} s",
                'HTTP 200 with {"status": "ok"}',
            )
        ]
        if ok:
            worker = body.get("worker")
            checks.append(
                Check(
                    "render_worker",
                    PASS if worker == "running" else FAIL,
                    f"worker={worker}",
                    "worker=running (otherwise queued reviews never run)",
                )
            )
        if cold_start:
            secs = response.seconds
            if response.status == 0:
                verdict = "no response at all"
            elif secs <= VERCEL_FORWARD_BUDGET_S:
                verdict = "within the Vercel forward budget"
            elif secs <= GITHUB_WEBHOOK_TIMEOUT_S:
                verdict = (
                    "over the Vercel forward budget: a webhook arriving while Render "
                    "sleeps gets 502 and is stored nowhere (architecture.md gap #1)"
                )
            else:
                verdict = (
                    "over GitHub's 10 s webhook timeout and the Vercel forward budget: "
                    "webhooks arriving while Render sleeps are lost (gap #1)"
                )
            checks.append(
                Check(
                    "render_cold_start",
                    INFO,
                    f"{secs:.1f} s to the first /health response after idling; {verdict}",
                    f"<= {VERCEL_FORWARD_BUDGET_S} s (Vercel forward budget), "
                    f"<= {GITHUB_WEBHOOK_TIMEOUT_S:.0f} s (GitHub)",
                )
            )
        return checks

    # --- Vercel -------------------------------------------------------------------
    def vercel_checks(self) -> list[Check]:
        if not self._vercel_url:
            return [Check("vercel_status", SKIP, "no --vercel-url / VERCEL_URL", "")]
        status = self._fetch(f"{self._vercel_url}/api/status", {})
        body = status.json()
        backend = body.get("backend") if isinstance(body, dict) else None
        route = self._fetch(f"{self._vercel_url}/api/github/webhook", {})
        return [
            Check(
                "vercel_status",
                PASS if status.status == 200 and backend == "ok" else FAIL,
                f"HTTP {status.status}, backend={backend}",
                "HTTP 200, backend=ok",
            ),
            Check(
                "vercel_webhook_route",
                PASS if route.status == 405 else FAIL,
                f"GET -> HTTP {route.status}",
                "HTTP 405 (route live; only POST is accepted)",
            ),
        ]

    # --- Supabase -----------------------------------------------------------------
    def database_checks(self, repo: str, pr_number: int, redelivered: str | None) -> list[Check]:
        if not (self._supabase_url and self._service_key):
            return [
                Check(
                    "database",
                    SKIP,
                    "SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY not set",
                    "",
                )
            ]
        checks: list[Check] = []

        repos = self._rows(
            "repositories", {"full_name": f"eq.{repo}", "select": "id,is_active"}
        )
        if not repos:
            observed = "query failed" if repos is None else "no row"
            return [Check("repository_row", FAIL, observed, f"one row for {repo}")]
        repository = repos[0]
        checks.append(
            Check(
                "repository_row",
                PASS if repository.get("is_active") else FAIL,
                f"is_active={repository.get('is_active')}",
                "row exists, is_active=true",
            )
        )

        prs = self._rows(
            "pull_requests",
            {
                "repository_id": f"eq.{repository['id']}",
                "github_pr_number": f"eq.{pr_number}",
                "select": "id,head_sha,state",
            },
        )
        if not prs:
            observed = "query failed" if prs is None else "no row"
            checks.append(Check("pull_request_row", FAIL, observed, f"PR #{pr_number}"))
            return checks
        pr = prs[0]
        head = pr.get("head_sha")
        checks.append(
            Check(
                "pull_request_row",
                PASS,
                f"head_sha={str(head)[:12]} state={pr.get('state')}",
                "row exists with the PR's head SHA",
            )
        )

        runs = self._rows(
            "review_runs",
            {
                "pull_request_id": f"eq.{pr['id']}",
                "select": "id,status,head_sha,merge_base_sha,attempts,error_code,"
                "error_message,analysis_meta,delivery_id,created_at",
                "order": "created_at.asc",
            },
        )
        checks.extend(self._run_checks(runs or [], head))
        head_runs = [r for r in (runs or []) if r.get("head_sha") == head]
        latest = head_runs[-1] if head_runs else None

        if latest and latest.get("status") in TERMINAL_OK + ("failed",):
            checks.append(self._findings_check(latest["id"]))

        checks.append(self._deliveries_check())
        if redelivered:
            checks.append(self._redelivery_check(redelivered, len(head_runs)))
        return checks

    def _run_checks(self, runs: list[dict], head: str | None) -> list[Check]:
        per_head = Counter(r.get("head_sha") for r in runs if r.get("head_sha"))
        duplicates = {sha: n for sha, n in per_head.items() if n > 1}
        checks = [
            Check(
                "one_review_run_per_head",
                FAIL if duplicates else PASS,
                f"runs={len(runs)}, duplicated heads={len(duplicates)}",
                "at most one review run per (pull request, head SHA)",
            )
        ]
        head_runs = [r for r in runs if r.get("head_sha") == head]
        if not head_runs:
            checks.append(Check("review_run_status", FAIL, "no run for the head SHA", ""))
            return checks
        run = head_runs[-1]
        status = run.get("status")
        meta = run.get("analysis_meta") or {}
        reasons = meta.get("incomplete_reasons") if isinstance(meta, dict) else None
        observed = f"status={status} attempts={run.get('attempts')}"
        if run.get("error_code"):
            observed += f" error_code={run.get('error_code')}"
        if status == "partial":
            observed += f" incomplete_reasons={_short(reasons)}"
        if status == "failed":
            observed += f" error_message={_short(run.get('error_message'))}"
        if status in TERMINAL_OK:
            verdict = PASS
        elif status in IN_FLIGHT:
            verdict = INFO
            observed += " (not finished yet: run this again in a minute)"
        else:
            verdict = FAIL
        checks.append(
            Check("review_run_status", verdict, observed, "completed (or partial with reasons)")
        )
        if status in TERMINAL_OK:
            pinned = bool(run.get("merge_base_sha")) and bool(meta)
            checks.append(
                Check(
                    "review_run_recorded",
                    PASS if pinned else FAIL,
                    f"merge_base_sha={'set' if run.get('merge_base_sha') else 'missing'}, "
                    f"analysis_meta={'set' if meta else 'missing'}",
                    "merge_base_sha and analysis_meta populated",
                )
            )
        return checks

    def _findings_check(self, run_id: str) -> Check:
        rows = self._rows(
            "findings", {"review_run_id": f"eq.{run_id}", "select": "change_status"}
        )
        if rows is None:
            return Check("findings", FAIL, "query failed", "")
        counts = Counter(str(r.get("change_status")) for r in rows)
        observed = ", ".join(f"{k}={v}" for k, v in sorted(counts.items())) or "0 rows"
        if not rows:
            return Check(
                "findings",
                INFO,
                "0 rows: the PR had nothing to find (open one with e.g. eval() to exercise "
                "this check)",
                "rows with change_status new / existing / fixed",
            )
        valid = set(counts) <= {"new", "existing", "fixed", "None"}
        return Check(
            "findings",
            PASS if valid else FAIL,
            observed,
            "rows with change_status new / existing / fixed",
        )

    def _deliveries_check(self) -> Check:
        rows = self._rows(
            "webhook_deliveries",
            {
                "event_type": "eq.pull_request",
                "select": "delivery_id,status,attempts,updated_at",
                "order": "updated_at.desc",
                "limit": "10",
            },
        )
        if rows is None:
            return Check("webhook_deliveries", FAIL, "query failed", "")
        if not rows:
            return Check("webhook_deliveries", FAIL, "no pull_request deliveries", "")
        stale_before = self._now() - timedelta(seconds=DELIVERY_LEASE_S)
        problems = []
        for row in rows:
            status = row.get("status")
            if status in ("failed", "retryable"):
                problems.append(f"{str(row.get('delivery_id'))[:8]}={status}")
            elif status == "processing" and _parse_ts(row.get("updated_at")) < stale_before:
                problems.append(f"{str(row.get('delivery_id'))[:8]}=stuck-processing")
        summary = Counter(str(r.get("status")) for r in rows)
        observed = ", ".join(f"{k}={v}" for k, v in sorted(summary.items()))
        if problems:
            observed += f"; problems: {', '.join(problems)}"
        newest_ok = rows[0].get("status") == "succeeded"
        return Check(
            "webhook_deliveries",
            PASS if newest_ok and not problems else FAIL,
            f"last {len(rows)}: {observed}",
            "newest succeeded; none failed, retryable, or stuck in processing",
        )

    def _redelivery_check(self, delivery_id: str, head_run_count: int) -> Check:
        rows = self._rows(
            "webhook_deliveries",
            {"delivery_id": f"eq.{delivery_id}", "select": "status,attempts"},
        )
        if not rows:
            return Check("redelivery_dedup", FAIL, "delivery id not found", "")
        row = rows[0]
        ok = row.get("status") == "succeeded" and head_run_count == 1
        return Check(
            "redelivery_dedup",
            PASS if ok else FAIL,
            f"delivery status={row.get('status')} attempts={row.get('attempts')}, "
            f"review runs for the head={head_run_count}",
            "delivery succeeded and still exactly one review run for the head SHA",
        )

    # --- Data API exposure (docs/architecture.md gap #10) --------------------------
    def exposure_check(self) -> Check:
        if not (self._supabase_url and self._anon_key):
            return Check("anon_data_api_closed", SKIP, "SUPABASE_ANON_KEY not set", "")
        response = self._rest(
            "webhook_deliveries", {"select": "id", "limit": "1"}, key=self._anon_key
        )
        closed = response.status in (401, 403)
        return Check(
            "anon_data_api_closed",
            PASS if closed else FAIL,
            f"anon GET webhook_deliveries -> HTTP {response.status}",
            "HTTP 401/403 (migration 0005 applied on this project)",
        )


def _parse_ts(value: object) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return datetime.max.replace(tzinfo=timezone.utc)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def run_checks(tg: TrackG, args: argparse.Namespace) -> list[Check]:
    checks = tg.render_checks(cold_start=args.cold_start)
    checks += tg.vercel_checks()
    checks += tg.database_checks(args.repo, args.pr, args.after_redelivery)
    checks.append(tg.exposure_check())
    return checks


def render_text(checks: list[Check]) -> str:
    width = max(len(c.name) for c in checks)
    lines = [f"{c.status:<4}  {c.name:<{width}}  {c.observed}" for c in checks]
    failed = sum(c.status == FAIL for c in checks)
    lines.append(f"\n{failed} failed, {len(checks)} checks")
    return "\n".join(lines)


def render_markdown(checks: list[Check], args: argparse.Namespace, when: datetime) -> str:
    rows = "\n".join(
        f"| `{c.name}` | {c.status} | {c.observed.replace('|', '/')} | {c.expected} |"
        for c in checks
    )
    return (
        f"### Track G check, {when.strftime('%Y-%m-%d %H:%M UTC')}\n\n"
        f"PR #{args.pr} on the test repository; cold-start measurement: "
        f"{'yes' if args.cold_start else 'no'}; after redelivery: "
        f"{'yes' if args.after_redelivery else 'no'}.\n\n"
        "| Check | Result | Observed | Expected |\n|---|---|---|---|\n"
        f"{rows}\n"
    )


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repo", required=True, help="owner/name of the TEST repository")
    parser.add_argument("--pr", type=int, required=True, help="pull request number")
    parser.add_argument("--render-url", default=os.environ.get("RENDER_URL"))
    parser.add_argument("--vercel-url", default=os.environ.get("VERCEL_URL"))
    parser.add_argument(
        "--cold-start",
        action="store_true",
        help="this run starts after Render has idled (>= 15 min): time the first /health",
    )
    parser.add_argument(
        "--after-redelivery",
        metavar="DELIVERY_ID",
        help="X-GitHub-Delivery id you clicked 'Redeliver' on; checks it was deduplicated",
    )
    parser.add_argument("--markdown", metavar="FILE", help="also append a Markdown table")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None, fetch: Fetch = http_get) -> int:
    args = parse_args(argv)
    tg = TrackG(
        fetch,
        supabase_url=os.environ.get("SUPABASE_URL"),
        service_key=os.environ.get("SUPABASE_SERVICE_ROLE_KEY"),
        anon_key=os.environ.get("SUPABASE_ANON_KEY"),
        render_url=args.render_url,
        vercel_url=args.vercel_url,
    )
    checks = run_checks(tg, args)
    print(render_text(checks))
    if args.markdown:
        with open(args.markdown, "a", encoding="utf-8") as handle:
            handle.write(render_markdown(checks, args, datetime.now(timezone.utc)) + "\n")
    return 1 if any(c.status == FAIL for c in checks) else 0


if __name__ == "__main__":
    sys.exit(main())

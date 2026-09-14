/**
 * Best-effort, per-installation rate limiting for the public webhook
 * endpoint. In-memory, process-local — NOT a strict global bound.
 *
 * Policy: max MAX_EVENTS_PER_WINDOW forwarded events per installation id
 * per WINDOW_MS. Chosen generously enough that a legitimate burst (e.g. a
 * repo's initial scan opening several PRs at once) sails through, while a
 * sustained flood from one installation gets throttled.
 *
 * Limitation (documented, not hidden): Vercel serverless functions are
 * ephemeral and may run as multiple concurrent instances, each with its own
 * copy of this Map. A warm instance enforces the limit correctly against
 * repeated invocations it personally handles; it cannot see traffic another
 * concurrent instance is handling. This bounds abuse from a single
 * hammering client in the common case but does not guarantee a strict
 * global limit under high concurrency or across cold starts.
 *
 * HMAC verification + minimal GitHub permissions remain the actual security
 * boundary; this is a DoS-cost-reduction measure, not a substitute for
 * those. Future improvement: move to a shared store (e.g. Upstash Redis's
 * free tier, or a Supabase-backed counter) if free-tier abuse in practice
 * warrants a real global limit — deliberately not done now per the Phase 2
 * scope boundary ("don't let rate limiting become an infrastructure
 * project").
 */

const WINDOW_MS = 60_000;
const MAX_EVENTS_PER_WINDOW = 30;

const buckets = new Map<string, number[]>();

export function isRateLimited(key: string, now: number = Date.now()): boolean {
  const timestamps = (buckets.get(key) ?? []).filter((t) => now - t < WINDOW_MS);

  if (timestamps.length >= MAX_EVENTS_PER_WINDOW) {
    buckets.set(key, timestamps);
    return true;
  }

  timestamps.push(now);
  buckets.set(key, timestamps);
  return false;
}

/** Test-only: reset all buckets between test cases. */
export function _resetRateLimitBucketsForTests(): void {
  buckets.clear();
}

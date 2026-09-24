// Access control for the internal (team-only) pages under /internal/*.
//
// Before Phase 0 the installations page had NO access control beyond an
// unlisted URL, yet it renders every installation and repository name the
// App can see. Now it is closed by default:
//
//   INTERNAL_PAGES_ENABLED != "true"      -> 404 (the route does not exist)
//   enabled, credentials not configured   -> 503 (fail closed; never open)
//   enabled, missing/wrong Basic auth     -> 401 + WWW-Authenticate
//   enabled, correct credentials          -> allowed
//
// Kept as a pure function (no Next/Edge imports) so it is unit-tested directly.
// This is HTTP Basic auth over HTTPS on a hobby-tier host: adequate for a
// team-only debug view, NOT a substitute for real authentication if this ever
// becomes a product surface.

export type InternalAccessConfig = {
  enabled: string | undefined;
  user: string | undefined;
  password: string | undefined;
};

export type InternalAccessDecision =
  | { allowed: true }
  | { allowed: false; status: 401 | 404 | 503; wwwAuthenticate?: string };

const REALM = 'Basic realm="codentry-internal", charset="UTF-8"';

/** Length-independent comparison so response timing does not leak a prefix match. */
export function constantTimeEqual(a: string, b: string): boolean {
  const encoder = new TextEncoder();
  const x = encoder.encode(a);
  const y = encoder.encode(b);
  let diff = x.length ^ y.length;
  const length = Math.max(x.length, y.length);
  for (let i = 0; i < length; i += 1) {
    diff |= (x[i] ?? 0) ^ (y[i] ?? 0);
  }
  return diff === 0;
}

function parseBasicAuth(header: string | null): { user: string; password: string } | null {
  if (!header || !header.toLowerCase().startsWith("basic ")) return null;
  try {
    const decoded = atob(header.slice(6).trim());
    const separator = decoded.indexOf(":");
    if (separator < 0) return null;
    return { user: decoded.slice(0, separator), password: decoded.slice(separator + 1) };
  } catch {
    return null;
  }
}

export function checkInternalAccess(
  config: InternalAccessConfig,
  authorizationHeader: string | null,
): InternalAccessDecision {
  if (config.enabled !== "true") {
    return { allowed: false, status: 404 };
  }
  if (!config.user || !config.password) {
    return { allowed: false, status: 503 };
  }

  const supplied = parseBasicAuth(authorizationHeader);
  if (!supplied) {
    return { allowed: false, status: 401, wwwAuthenticate: REALM };
  }

  // Evaluate both comparisons unconditionally (no short-circuit).
  const userOk = constantTimeEqual(supplied.user, config.user);
  const passwordOk = constantTimeEqual(supplied.password, config.password);
  if (userOk && passwordOk) {
    return { allowed: true };
  }
  return { allowed: false, status: 401, wwwAuthenticate: REALM };
}

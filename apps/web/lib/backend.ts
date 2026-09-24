// Thin client for talking to services/ai-review. This is the one place the
// Phase 1 "frontend -> backend network path" requirement is implemented, so
// both the /api/status route and the landing page share exactly one code
// path instead of the page calling its own API route over HTTP.

// `error` is for server-side logs and tests ONLY. Public surfaces (the home
// page, /api/status) must render just "ok"/"unreachable" and never echo it:
// it can contain the backend URL, hostnames, and network error text.
export type BackendHealth = {
  ok: boolean;
  data?: unknown;
  error?: string;
};

const DEFAULT_BACKEND_URL = "http://localhost:8000";
const REQUEST_TIMEOUT_MS = 3000;

function getBackendBaseUrl(): string {
  return process.env.NEXT_PUBLIC_API_BASE_URL ?? DEFAULT_BACKEND_URL;
}

export async function getBackendHealth(): Promise<BackendHealth> {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);

  try {
    const response = await fetch(`${getBackendBaseUrl()}/health`, {
      cache: "no-store",
      signal: controller.signal,
    });

    if (!response.ok) {
      const error = `backend responded with status ${response.status}`;
      console.error(JSON.stringify({ logger: "codentry.web.backend", error }));
      return { ok: false, error };
    }

    const data = await response.json();
    return { ok: true, data };
  } catch (err) {
    const message = err instanceof Error ? err.message : "unknown error";
    const error = `could not reach backend: ${message}`;
    console.error(JSON.stringify({ logger: "codentry.web.backend", error }));
    return { ok: false, error };
  } finally {
    clearTimeout(timeout);
  }
}

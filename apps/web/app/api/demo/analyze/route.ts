import { NextRequest, NextResponse } from "next/server";

const DEFAULT_BACKEND_URL = "http://localhost:8000";
const REQUEST_TIMEOUT_MS = 60_000; // cold ESLint/Semgrep starts can take tens of seconds

function backendBaseUrl(): string {
  return process.env.NEXT_PUBLIC_API_BASE_URL ?? DEFAULT_BACKEND_URL;
}

// Proxies to the backend's dev-only /demo/analyze route, which runs the real
// static-analysis engine against the real fixtures in analysis/fixtures/.
// Nothing here duplicates ESLint/Semgrep logic — this route only forwards.
export async function GET(req: NextRequest) {
  const fixture = req.nextUrl.searchParams.get("fixture") ?? "all";
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);

  try {
    const res = await fetch(
      `${backendBaseUrl()}/demo/analyze?fixture=${encodeURIComponent(fixture)}`,
      { cache: "no-store", signal: controller.signal },
    );
    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      return NextResponse.json(
        { error: body.detail ?? "the backend demo endpoint is not available (is it running in development mode?)" },
        { status: res.status === 400 ? 400 : 503 },
      );
    }
    return NextResponse.json(await res.json());
  } catch {
    return NextResponse.json({ error: "could not reach the backend, or the analysis timed out" }, { status: 503 });
  } finally {
    clearTimeout(timeout);
  }
}

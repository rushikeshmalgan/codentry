import { NextResponse } from "next/server";

const DEFAULT_BACKEND_URL = "http://localhost:8000";

function backendBaseUrl(): string {
  return process.env.NEXT_PUBLIC_API_BASE_URL ?? DEFAULT_BACKEND_URL;
}

// Proxies to the backend's dev-only /demo/fixtures route (see
// services/ai-review/app/routes_demo.py). Kept server-side so the backend URL
// never has to be exposed to the browser directly.
export async function GET() {
  try {
    const res = await fetch(`${backendBaseUrl()}/demo/fixtures`, { cache: "no-store" });
    if (!res.ok) {
      return NextResponse.json(
        { error: "the backend demo endpoint is not available (is it running in development mode?)" },
        { status: 503 },
      );
    }
    return NextResponse.json(await res.json());
  } catch {
    return NextResponse.json({ error: "could not reach the backend" }, { status: 503 });
  }
}

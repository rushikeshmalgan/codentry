import { NextResponse } from "next/server";
import { getBackendHealth } from "@/lib/backend";

// Public liveness endpoint proving the apps/web -> services/ai-review network
// path is real. It is unauthenticated, so it reports ONLY "ok" or
// "unreachable": never the backend's URL, an error message, a status code, or
// any field of the backend's own response. Diagnostic detail goes to the
// server log (lib/backend.ts), not to the caller.
export async function GET() {
  const backend = await getBackendHealth();

  if (!backend.ok) {
    return NextResponse.json({ web: "ok", backend: "unreachable" }, { status: 503 });
  }

  return NextResponse.json({ web: "ok", backend: "ok" });
}

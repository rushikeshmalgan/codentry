import { NextResponse } from "next/server";
import { getBackendHealth } from "@/lib/backend";

// Phase 1 scaffold endpoint proving the apps/web -> services/ai-review
// network path is real. Not part of the GitHub review pipeline — that
// arrives in Phase 2 onward.
export async function GET() {
  const backend = await getBackendHealth();

  if (!backend.ok) {
    return NextResponse.json(
      { web: "ok", backend: "unreachable", detail: backend.error },
      { status: 503 },
    );
  }

  return NextResponse.json({ web: "ok", backend: "ok", backendHealth: backend.data });
}

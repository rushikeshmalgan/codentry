import { NextResponse } from "next/server";

// Phase 1 stub only. Signature verification, event handling, and the
// async hand-off to services/ai-review are implemented in Phase 2 —
// see docs/ for the roadmap. This route exists now purely to reserve the
// path GitHub's webhook will eventually be configured to call.
export async function POST() {
  return NextResponse.json(
    {
      error: "not_implemented",
      message: "GitHub webhook handling arrives in Phase 2.",
    },
    { status: 501 },
  );
}

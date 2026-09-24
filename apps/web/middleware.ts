import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";
import { checkInternalAccess } from "@/lib/internal-access";

// Gates every /internal/* page. See lib/internal-access.ts for the policy:
// closed (404) unless INTERNAL_PAGES_ENABLED=true, then HTTP Basic auth.
export function middleware(request: NextRequest): NextResponse {
  const decision = checkInternalAccess(
    {
      enabled: process.env.INTERNAL_PAGES_ENABLED,
      user: process.env.INTERNAL_PAGES_USER,
      password: process.env.INTERNAL_PAGES_PASSWORD,
    },
    request.headers.get("authorization"),
  );

  if (decision.allowed) {
    return NextResponse.next();
  }

  const headers: Record<string, string> = { "Cache-Control": "no-store" };
  if (decision.wwwAuthenticate) {
    headers["WWW-Authenticate"] = decision.wwwAuthenticate;
  }
  // Deliberately no body detail: a closed page should look like a missing page.
  return new NextResponse(decision.status === 404 ? "Not found" : "Unauthorized", {
    status: decision.status,
    headers,
  });
}

export const config = {
  matcher: ["/internal/:path*"],
};

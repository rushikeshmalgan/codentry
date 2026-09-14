import { describe, expect, it } from "vitest";
import { POST } from "../app/api/github/webhook/route";

describe("POST /api/github/webhook (Phase 1 stub)", () => {
  it("returns 501 not_implemented until Phase 2 lands", async () => {
    const response = await POST();
    const body = await response.json();

    expect(response.status).toBe(501);
    expect(body.error).toBe("not_implemented");
  });
});

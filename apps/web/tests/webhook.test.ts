import { createHmac } from "node:crypto";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { _resetRateLimitBucketsForTests } from "../lib/rate-limit";

const SECRET = "test-webhook-secret";

function sign(body: string, secret: string = SECRET): string {
  return "sha256=" + createHmac("sha256", secret).update(body, "utf8").digest("hex");
}

function makeRequest(body: string, headers: Record<string, string>): Request {
  return new Request("http://localhost/api/github/webhook", { method: "POST", headers, body });
}

vi.mock("@/lib/internal-client", () => ({
  forwardToInternalApi: vi.fn(),
}));

const { forwardToInternalApi } = await import("@/lib/internal-client");
const { POST } = await import("../app/api/github/webhook/route");

const mockForward = forwardToInternalApi as unknown as ReturnType<typeof vi.fn>;

describe("POST /api/github/webhook", () => {
  const originalSecret = process.env.GITHUB_WEBHOOK_SECRET;

  beforeEach(() => {
    process.env.GITHUB_WEBHOOK_SECRET = SECRET;
    mockForward.mockReset();
    _resetRateLimitBucketsForTests();
  });

  afterEach(() => {
    process.env.GITHUB_WEBHOOK_SECRET = originalSecret;
  });

  it("returns 503 when GITHUB_WEBHOOK_SECRET is not configured", async () => {
    delete process.env.GITHUB_WEBHOOK_SECRET;
    const body = JSON.stringify({ a: 1 });
    const req = makeRequest(body, {
      "x-github-event": "pull_request",
      "x-github-delivery": "d1",
      "x-hub-signature-256": sign(body),
    });

    const res = await POST(req);
    expect(res.status).toBe(503);
  });

  it("returns 400 when required GitHub headers are missing", async () => {
    const body = "{}";
    const req = makeRequest(body, { "x-hub-signature-256": sign(body) });

    const res = await POST(req);
    expect(res.status).toBe(400);
  });

  it("returns 401 for a missing signature", async () => {
    const req = makeRequest("{}", { "x-github-event": "pull_request", "x-github-delivery": "d1" });
    const res = await POST(req);
    expect(res.status).toBe(401);
  });

  it("returns 401 for an invalid signature", async () => {
    const req = makeRequest("{}", {
      "x-github-event": "pull_request",
      "x-github-delivery": "d1",
      "x-hub-signature-256": "sha256=" + "0".repeat(64),
    });
    const res = await POST(req);
    expect(res.status).toBe(401);
  });

  it("returns 401 for a malformed signature", async () => {
    const req = makeRequest("{}", {
      "x-github-event": "pull_request",
      "x-github-delivery": "d1",
      "x-hub-signature-256": "not-a-real-signature",
    });
    const res = await POST(req);
    expect(res.status).toBe(401);
  });

  it("returns 401 when the payload was modified after signing", async () => {
    const originalBody = JSON.stringify({ action: "opened" });
    const tamperedBody = JSON.stringify({ action: "closed" });
    const req = makeRequest(tamperedBody, {
      "x-github-event": "pull_request",
      "x-github-delivery": "d1",
      "x-hub-signature-256": sign(originalBody),
    });
    const res = await POST(req);
    expect(res.status).toBe(401);
    expect(mockForward).not.toHaveBeenCalled();
  });

  it("acknowledges ping events without forwarding", async () => {
    const body = JSON.stringify({ zen: "Anything added dilutes everything else." });
    const req = makeRequest(body, {
      "x-github-event": "ping",
      "x-github-delivery": "d1",
      "x-hub-signature-256": sign(body),
    });
    const res = await POST(req);
    expect(res.status).toBe(200);
    expect(mockForward).not.toHaveBeenCalled();
  });

  it("acknowledges unsupported event types without forwarding", async () => {
    const body = JSON.stringify({});
    const req = makeRequest(body, {
      "x-github-event": "issues",
      "x-github-delivery": "d1",
      "x-hub-signature-256": sign(body),
    });
    const res = await POST(req);
    expect(res.status).toBe(200);
    const json = await res.json();
    expect(json.status).toBe("ignored");
    expect(mockForward).not.toHaveBeenCalled();
  });

  it("forwards a valid pull_request event and passes through the backend's response", async () => {
    mockForward.mockResolvedValue({
      ok: true,
      status: 202,
      body: { status: "accepted", review_run_id: "run-abc" },
    });
    const payload = { action: "opened", installation: { id: 42 } };
    const body = JSON.stringify(payload);
    const req = makeRequest(body, {
      "x-github-event": "pull_request",
      "x-github-delivery": "d1",
      "x-hub-signature-256": sign(body),
    });

    const res = await POST(req);

    expect(res.status).toBe(202);
    const json = await res.json();
    expect(json.review_run_id).toBe("run-abc");
    expect(mockForward).toHaveBeenCalledWith("d1", "pull_request", payload);
  });

  it("returns 502 (not a fabricated 200) when forwarding fails", async () => {
    mockForward.mockResolvedValue({ ok: false, reason: "network_error" });
    const body = JSON.stringify({ action: "opened", installation: { id: 42 } });
    const req = makeRequest(body, {
      "x-github-event": "pull_request",
      "x-github-delivery": "d1",
      "x-hub-signature-256": sign(body),
    });

    const res = await POST(req);
    expect(res.status).toBe(502);
  });

  it("rate-limits repeated events from the same installation", async () => {
    mockForward.mockResolvedValue({ ok: true, status: 202, body: { status: "accepted" } });
    let lastStatus = 0;

    for (let i = 0; i < 31; i++) {
      const body = JSON.stringify({ action: "opened", installation: { id: 999 }, n: i });
      const req = makeRequest(body, {
        "x-github-event": "pull_request",
        "x-github-delivery": `d-${i}`,
        "x-hub-signature-256": sign(body),
      });
      lastStatus = (await POST(req)).status;
    }

    expect(lastStatus).toBe(429);
  });
});

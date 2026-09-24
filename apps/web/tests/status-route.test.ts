import { afterEach, describe, expect, it, vi } from "vitest";
import { GET } from "../app/api/status/route";

describe("GET /api/status (public)", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("reports only ok/ok when the backend is healthy, without echoing backend fields", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        json: async () => ({ status: "ok", service: "x", environment: "production", secret: "no" }),
      }),
    );

    const response = await GET();
    const body = await response.json();

    expect(response.status).toBe(200);
    expect(body).toEqual({ web: "ok", backend: "ok" });
  });

  it("never leaks the backend URL or the network error when the backend is down", async () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    vi.stubGlobal(
      "fetch",
      vi.fn().mockRejectedValue(new Error("connect ECONNREFUSED 10.0.0.7:8000 (codentry-internal.onrender.com)")),
    );

    const response = await GET();
    const text = JSON.stringify(await response.json());

    expect(response.status).toBe(503);
    expect(JSON.parse(text)).toEqual({ web: "ok", backend: "unreachable" });
    expect(text).not.toMatch(/ECONNREFUSED|onrender|10\.0\.0\.7|codentry-internal/);
  });

  it("never leaks a backend status code either", async () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: false, status: 502, json: async () => ({}) }));

    const response = await GET();
    const text = JSON.stringify(await response.json());

    expect(text).not.toContain("502");
    expect(JSON.parse(text)).toEqual({ web: "ok", backend: "unreachable" });
  });

  it("logs the diagnostic detail server-side instead", async () => {
    const spy = vi.spyOn(console, "error").mockImplementation(() => {});
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("boom")));

    await GET();

    expect(spy).toHaveBeenCalled();
    expect(String(spy.mock.calls[0][0])).toContain("boom");
  });
});

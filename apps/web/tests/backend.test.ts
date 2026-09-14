import { afterEach, describe, expect, it, vi } from "vitest";
import { getBackendHealth } from "../lib/backend";

describe("getBackendHealth", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("returns ok:true with the backend payload on a healthy response", async () => {
    const mockFetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ status: "ok", service: "codentry-ai-review" }),
    });
    vi.stubGlobal("fetch", mockFetch);

    const result = await getBackendHealth();

    expect(result.ok).toBe(true);
    expect(result.data).toEqual({ status: "ok", service: "codentry-ai-review" });
    expect(mockFetch).toHaveBeenCalledWith(
      expect.stringMatching(/\/health$/),
      expect.objectContaining({ cache: "no-store" }),
    );
  });

  it("returns ok:false when the backend responds with a non-2xx status", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({ ok: false, status: 500, json: async () => ({}) }),
    );

    const result = await getBackendHealth();

    expect(result.ok).toBe(false);
    expect(result.error).toContain("500");
  });

  it("returns ok:false when the fetch itself throws (backend unreachable)", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockRejectedValue(new Error("ECONNREFUSED")),
    );

    const result = await getBackendHealth();

    expect(result.ok).toBe(false);
    expect(result.error).toContain("ECONNREFUSED");
  });
});

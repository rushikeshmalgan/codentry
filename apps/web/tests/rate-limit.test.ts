import { beforeEach, describe, expect, it } from "vitest";
import { _resetRateLimitBucketsForTests, isRateLimited } from "../lib/rate-limit";

describe("isRateLimited", () => {
  beforeEach(() => {
    _resetRateLimitBucketsForTests();
  });

  it("allows requests under the limit", () => {
    for (let i = 0; i < 30; i++) {
      expect(isRateLimited("install-1", 1_000)).toBe(false);
    }
  });

  it("blocks once the limit is exceeded within the window", () => {
    for (let i = 0; i < 30; i++) isRateLimited("install-2", 1_000);
    expect(isRateLimited("install-2", 1_000)).toBe(true);
  });

  it("uses independent buckets per key", () => {
    for (let i = 0; i < 30; i++) isRateLimited("install-3", 1_000);
    expect(isRateLimited("install-4", 1_000)).toBe(false);
  });

  it("allows requests again once the window has passed", () => {
    for (let i = 0; i < 30; i++) isRateLimited("install-5", 1_000);
    expect(isRateLimited("install-5", 1_000)).toBe(true);
    expect(isRateLimited("install-5", 1_000 + 60_001)).toBe(false);
  });
});

import { describe, expect, it } from "vitest";
import { checkInternalAccess, constantTimeEqual } from "../lib/internal-access";

const basic = (user: string, password: string) =>
  `Basic ${Buffer.from(`${user}:${password}`).toString("base64")}`;

const enabled = { enabled: "true", user: "team", password: "s3cret-passphrase" };

describe("checkInternalAccess", () => {
  it("is closed (404) unless explicitly enabled", () => {
    for (const value of [undefined, "", "false", "TRUE", "1", "yes"]) {
      const decision = checkInternalAccess({ ...enabled, enabled: value }, basic("team", "s3cret-passphrase"));
      expect(decision).toEqual({ allowed: false, status: 404 });
    }
  });

  it("fails closed (503) when enabled but credentials are not configured", () => {
    expect(checkInternalAccess({ enabled: "true", user: undefined, password: "x" }, basic("a", "x"))).toEqual({
      allowed: false,
      status: 503,
    });
    expect(checkInternalAccess({ enabled: "true", user: "u", password: "" }, basic("u", ""))).toEqual({
      allowed: false,
      status: 503,
    });
  });

  it("never allows an empty-credential request, even against empty config", () => {
    const decision = checkInternalAccess({ enabled: "true", user: "", password: "" }, basic("", ""));
    expect(decision.allowed).toBe(false);
  });

  it("challenges (401 + WWW-Authenticate) when there is no or malformed Authorization", () => {
    for (const header of [null, "", "Bearer abc", "Basic", "Basic !!!not-base64!!!", `Basic ${btoa("nocolon")}`]) {
      const decision = checkInternalAccess(enabled, header);
      expect(decision.allowed).toBe(false);
      if (!decision.allowed) {
        expect(decision.status).toBe(401);
        expect(decision.wwwAuthenticate).toContain("Basic");
      }
    }
  });

  it("rejects wrong user, wrong password, and near-misses", () => {
    for (const header of [
      basic("team", "wrong"),
      basic("other", "s3cret-passphrase"),
      basic("team", "s3cret-passphrase "),
      basic("team", "s3cret-passphras"),
      basic("Team", "s3cret-passphrase"),
    ]) {
      expect(checkInternalAccess(enabled, header)).toMatchObject({ allowed: false, status: 401 });
    }
  });

  it("allows the exact credentials, including passwords containing colons", () => {
    expect(checkInternalAccess(enabled, basic("team", "s3cret-passphrase"))).toEqual({ allowed: true });
    const withColon = { enabled: "true", user: "team", password: "a:b:c" };
    expect(checkInternalAccess(withColon, basic("team", "a:b:c"))).toEqual({ allowed: true });
  });

  it("accepts the scheme case-insensitively", () => {
    const header = basic("team", "s3cret-passphrase").replace("Basic", "basic");
    expect(checkInternalAccess(enabled, header)).toEqual({ allowed: true });
  });
});

describe("constantTimeEqual", () => {
  it("matches only identical strings", () => {
    expect(constantTimeEqual("abc", "abc")).toBe(true);
    expect(constantTimeEqual("abc", "abd")).toBe(false);
    expect(constantTimeEqual("abc", "abcd")).toBe(false);
    expect(constantTimeEqual("", "")).toBe(true);
    expect(constantTimeEqual("", "a")).toBe(false);
    expect(constantTimeEqual("é", "é")).toBe(true);
  });
});

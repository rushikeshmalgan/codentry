import { createHmac } from "node:crypto";
import { describe, expect, it } from "vitest";
import { isSupportedEventType, verifySignature } from "../lib/github-webhook";

const SECRET = "unit-test-secret";

function sign(body: string, secret: string = SECRET): string {
  return "sha256=" + createHmac("sha256", secret).update(body, "utf8").digest("hex");
}

describe("verifySignature", () => {
  it("accepts a correctly signed body", () => {
    const body = JSON.stringify({ action: "opened" });
    expect(verifySignature(body, sign(body), SECRET)).toBe(true);
  });

  it("rejects a signature computed with the wrong secret", () => {
    const body = JSON.stringify({ action: "opened" });
    expect(verifySignature(body, sign(body, "a-different-secret"), SECRET)).toBe(false);
  });

  it("rejects a missing signature", () => {
    expect(verifySignature("{}", null, SECRET)).toBe(false);
  });

  it("rejects a malformed signature missing the sha256= prefix", () => {
    expect(verifySignature("{}", "deadbeef", SECRET)).toBe(false);
  });

  it("rejects a malformed signature with non-hex content", () => {
    expect(verifySignature("{}", "sha256=not-hex-garbage!!!", SECRET)).toBe(false);
  });

  it("rejects a signature whose payload was modified after signing", () => {
    const originalBody = JSON.stringify({ action: "opened" });
    const modifiedBody = JSON.stringify({ action: "closed" });
    expect(verifySignature(modifiedBody, sign(originalBody), SECRET)).toBe(false);
  });
});

describe("isSupportedEventType", () => {
  it("accepts the three subscribed event types", () => {
    expect(isSupportedEventType("pull_request")).toBe(true);
    expect(isSupportedEventType("installation")).toBe(true);
    expect(isSupportedEventType("installation_repositories")).toBe(true);
  });

  it("rejects anything Codentry did not subscribe to", () => {
    expect(isSupportedEventType("push")).toBe(false);
    expect(isSupportedEventType("issues")).toBe(false);
  });
});

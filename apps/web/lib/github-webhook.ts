import { createHmac, timingSafeEqual } from "node:crypto";

const SIGNATURE_PREFIX = "sha256=";

/**
 * Verifies a GitHub webhook signature against the RAW request body bytes.
 *
 * CRITICAL: `rawBody` must be exactly what GitHub sent — never
 * `JSON.parse()` then `JSON.stringify()`'d, which can reorder keys or
 * change whitespace and silently break every signature. The caller must
 * obtain this via `request.text()` before any parsing happens.
 */
export function verifySignature(
  rawBody: string,
  signatureHeader: string | null,
  secret: string,
): boolean {
  if (!signatureHeader || !signatureHeader.startsWith(SIGNATURE_PREFIX)) {
    return false;
  }

  const receivedHex = signatureHeader.slice(SIGNATURE_PREFIX.length);
  const expectedHex = createHmac("sha256", secret).update(rawBody, "utf8").digest("hex");

  // Buffers must be equal length for timingSafeEqual, or it throws. A
  // length mismatch just means "not equal" — checking it first isn't a
  // meaningful timing leak (signature length reveals nothing about its
  // content), and avoids the throw entirely.
  const receivedBuf = Buffer.from(receivedHex, "hex");
  const expectedBuf = Buffer.from(expectedHex, "hex");
  if (receivedBuf.length !== expectedBuf.length) {
    return false;
  }

  return timingSafeEqual(receivedBuf, expectedBuf);
}

export const SUPPORTED_EVENT_TYPES = ["pull_request", "installation", "installation_repositories"] as const;
export type SupportedEventType = (typeof SUPPORTED_EVENT_TYPES)[number];

export function isSupportedEventType(eventType: string): eventType is SupportedEventType {
  return (SUPPORTED_EVENT_TYPES as readonly string[]).includes(eventType);
}

import type { SupportedEventType } from "./github-webhook";

export type InternalForwardResult =
  | { ok: true; status: number; body: unknown }
  | { ok: false; reason: "timeout" | "network_error" | "backend_error"; status?: number };

const FORWARD_TIMEOUT_MS = 4000;
const RETRY_DELAY_MS = 300;

function getApiBaseUrl(): string {
  return process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";
}

function getInternalSecret(): string | undefined {
  // Server-only. Never read from a NEXT_PUBLIC_* variable.
  return process.env.CODENTRY_INTERNAL_WEBHOOK_SECRET;
}

async function attemptForward(
  deliveryId: string,
  eventType: SupportedEventType,
  payload: unknown,
): Promise<InternalForwardResult> {
  const secret = getInternalSecret();
  if (!secret) {
    // Fail closed, same principle as the backend's require_internal_secret:
    // an unconfigured secret must never be silently skipped.
    return { ok: false, reason: "backend_error" };
  }

  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), FORWARD_TIMEOUT_MS);

  try {
    const response = await fetch(`${getApiBaseUrl()}/internal/webhook/pull-request`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Codentry-Internal-Secret": secret,
      },
      body: JSON.stringify({ delivery_id: deliveryId, event_type: eventType, payload }),
      signal: controller.signal,
    });

    const body = await response.json().catch(() => null);

    if (response.status >= 500) {
      return { ok: false, reason: "backend_error", status: response.status };
    }

    return { ok: true, status: response.status, body };
  } catch (err) {
    if (err instanceof Error && err.name === "AbortError") {
      return { ok: false, reason: "timeout" };
    }
    return { ok: false, reason: "network_error" };
  } finally {
    clearTimeout(timeout);
  }
}

/**
 * Forwards a verified webhook event to services/ai-review, with one quick
 * retry on failure. Total worst case (timeout + retry + timeout) stays well
 * under GitHub's 10s budget: 4s + 0.3s + 4s = 8.3s.
 *
 * ARCHITECTURAL HONESTY: if both attempts fail, this event is NOT durably
 * queued anywhere Codentry controls. There is no retry beyond this
 * function. The caller (the webhook route) must respond to GitHub with a
 * real failure status in that case — see route.ts — so GitHub's own
 * delivery log records it as failed and a human can use "Redeliver" from
 * the GitHub App's Advanced settings. Silently returning 200 here would be
 * a lie: the event would be gone with no way to know it ever happened.
 */
export async function forwardToInternalApi(
  deliveryId: string,
  eventType: SupportedEventType,
  payload: unknown,
): Promise<InternalForwardResult> {
  const first = await attemptForward(deliveryId, eventType, payload);
  if (first.ok) {
    return first;
  }

  await new Promise((resolve) => setTimeout(resolve, RETRY_DELAY_MS));
  return attemptForward(deliveryId, eventType, payload);
}

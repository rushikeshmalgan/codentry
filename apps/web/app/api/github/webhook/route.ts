import { NextResponse } from "next/server";
import { forwardToInternalApi } from "@/lib/internal-client";
import { isSupportedEventType, verifySignature } from "@/lib/github-webhook";
import { isRateLimited } from "@/lib/rate-limit";

/**
 * The public GitHub webhook receiver. Verifies the request, then hands it
 * off to services/ai-review and gets out of the way — GitHub's ~10s
 * timeout budget is spent almost entirely on the single forward call below,
 * not on doing any actual review work here (there is none to do at this
 * layer; see docs/ for the full pipeline).
 */
export async function POST(request: Request): Promise<NextResponse> {
  // CRITICAL: read the raw body ONCE, before any parsing. HMAC is computed
  // over these exact bytes. Never JSON.parse() then JSON.stringify() this —
  // that can reorder keys or change whitespace and silently break every
  // signature GitHub ever sends.
  const rawBody = await request.text();

  const signature = request.headers.get("x-hub-signature-256");
  const deliveryId = request.headers.get("x-github-delivery");
  const eventType = request.headers.get("x-github-event");

  const secret = process.env.GITHUB_WEBHOOK_SECRET;
  if (!secret) {
    logWebhookEvent({ status: "rejected", reason: "webhook_secret_not_configured" });
    return NextResponse.json({ error: "webhook_not_configured" }, { status: 503 });
  }

  if (!deliveryId || !eventType) {
    logWebhookEvent({ status: "rejected", reason: "missing_required_headers" });
    return NextResponse.json({ error: "missing_required_headers" }, { status: 400 });
  }

  if (!verifySignature(rawBody, signature, secret)) {
    logWebhookEvent({ event_type: eventType, delivery_id: deliveryId, status: "rejected", reason: "invalid_signature" });
    return NextResponse.json({ error: "invalid_signature" }, { status: 401 });
  }

  // GitHub sends `ping` once when a webhook is first configured. Ack it
  // directly — there's nothing to bookkeep and nothing to forward.
  if (eventType === "ping") {
    logWebhookEvent({ event_type: eventType, delivery_id: deliveryId, status: "ping_acknowledged" });
    return NextResponse.json({ status: "pong" }, { status: 200 });
  }

  if (!isSupportedEventType(eventType)) {
    // Codentry's App is only subscribed to pull_request / installation /
    // installation_repositories, so this shouldn't normally happen — but
    // if GitHub ever sends something else, ack it quietly rather than
    // erroring, per "unsupported events should be handled safely."
    logWebhookEvent({ event_type: eventType, delivery_id: deliveryId, status: "ignored", reason: "unsupported_event_type" });
    return NextResponse.json({ status: "ignored" }, { status: 200 });
  }

  let payload: unknown;
  try {
    payload = JSON.parse(rawBody);
  } catch {
    logWebhookEvent({ event_type: eventType, delivery_id: deliveryId, status: "rejected", reason: "invalid_json" });
    return NextResponse.json({ error: "invalid_json" }, { status: 400 });
  }

  const installationId = extractInstallationId(payload);
  const rateLimitKey = installationId !== null ? String(installationId) : "unknown";
  if (isRateLimited(rateLimitKey)) {
    logWebhookEvent({
      event_type: eventType,
      delivery_id: deliveryId,
      installation_id: installationId,
      status: "rejected",
      reason: "rate_limited",
    });
    return NextResponse.json({ error: "rate_limited" }, { status: 429 });
  }

  const startedAt = Date.now();
  const result = await forwardToInternalApi(deliveryId, eventType, payload);
  const latencyMs = Date.now() - startedAt;

  if (!result.ok) {
    // ARCHITECTURAL HONESTY: this event is not durably queued anywhere.
    // Returning a real failure status (not a lied-about 200) means GitHub
    // records the delivery as failed in its own dashboard, where a human
    // can manually redeliver it — see docs/staging-test-phase2.md. There is
    // no automatic retry beyond the one immediate retry already attempted
    // inside forwardToInternalApi.
    logWebhookEvent({
      event_type: eventType,
      delivery_id: deliveryId,
      installation_id: installationId,
      status: "forward_failed",
      reason: result.reason,
      latency_ms: latencyMs,
    });
    return NextResponse.json({ error: "backend_unavailable" }, { status: 502 });
  }

  logWebhookEvent({
    event_type: eventType,
    delivery_id: deliveryId,
    installation_id: installationId,
    status: "forwarded",
    latency_ms: latencyMs,
  });

  return NextResponse.json(result.body ?? { status: "accepted" }, { status: result.status });
}

function extractInstallationId(payload: unknown): number | null {
  if (typeof payload !== "object" || payload === null) return null;
  const installation = (payload as Record<string, unknown>).installation;
  if (typeof installation !== "object" || installation === null) return null;
  const id = (installation as Record<string, unknown>).id;
  return typeof id === "number" ? id : null;
}

/**
 * Structured JSON log line, mirroring services/ai-review's format. Never
 * includes: the signature header, the webhook secret, the internal secret,
 * or the raw payload body — only routing metadata.
 */
function logWebhookEvent(fields: Record<string, unknown>): void {
  console.log(
    JSON.stringify({ timestamp: new Date().toISOString(), logger: "codentry.web.webhook", ...fields }),
  );
}

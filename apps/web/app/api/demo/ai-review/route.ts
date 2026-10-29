import { NextRequest, NextResponse } from "next/server";
import { buildMessages, verifyFindings, type SourceFile } from "@/lib/ai-review";

const DEFAULT_BACKEND_URL = "http://localhost:8000";
const DEFAULT_OLLAMA_URL = "http://localhost:11434";
const DEFAULT_MODEL = "qwen2.5-coder:7b";
const OLLAMA_TIMEOUT_MS = 120_000; // local inference on a laptop can take 30–90s

// Same fixture ids as _FIXTURE_FILES in services/ai-review/app/routes_demo.py.
const FIXTURE_FILES = new Map<string, string[]>([
  ["all", ["eslint_sample.js", "semgrep_sample.js", "clean_sample.js"]],
  ["eslint", ["eslint_sample.js"]],
  ["semgrep", ["semgrep_sample.js"]],
  ["clean", ["clean_sample.js"]],
  ["logic", ["logic_sample.js"]],
  ["calc", ["calc_pr_sample.js"]],
]);

function backendBaseUrl(): string {
  return process.env.NEXT_PUBLIC_API_BASE_URL ?? DEFAULT_BACKEND_URL;
}

// Local demo only: the AI arm (experimental). Reviews the checked-in fixtures
// with a local model through Ollama; nothing user-supplied is ever sent.
// The code comes from the backend's dev-only /demo/fixtures route, so in
// production (where that route does not exist) this returns 503 before any model call.
// The AI call deliberately lives here, not in the Python service (see test_scope_guards.py).
export async function GET(req: NextRequest) {
  const fixture = req.nextUrl.searchParams.get("fixture") ?? "logic";
  const filenames = FIXTURE_FILES.get(fixture);
  if (!filenames) {
    return NextResponse.json({ error: `unknown fixture "${fixture}"` }, { status: 400 });
  }

  const files = await loadFixtureFiles(filenames);
  if (!files) {
    return NextResponse.json(
      { error: "could not load the fixtures from the backend (is it running in development mode?)" },
      { status: 503 },
    );
  }

  const model = process.env.OLLAMA_MODEL ?? DEFAULT_MODEL;
  const started = Date.now();
  const reply = await callOllama(model, files);
  if ("error" in reply) {
    return NextResponse.json({ error: reply.error }, { status: reply.status });
  }

  const { findings, discarded_count, error } = verifyFindings(reply.content, files);
  return NextResponse.json({ findings, discarded_count, error, model: reply.model, elapsed_ms: Date.now() - started });
}

async function loadFixtureFiles(filenames: string[]): Promise<SourceFile[] | null> {
  try {
    const res = await fetch(`${backendBaseUrl()}/demo/fixtures`, { cache: "no-store" });
    if (!res.ok) return null;
    const body: { fixtures: SourceFile[] } = await res.json();
    const files = body.fixtures
      .filter((f) => filenames.includes(f.filename))
      .map(({ filename, source }) => ({ filename, source }));
    return files.length === filenames.length ? files : null;
  } catch {
    return null;
  }
}

type OllamaReply = { content: string; model: string } | { error: string; status: number };

async function callOllama(model: string, files: SourceFile[]): Promise<OllamaReply> {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), OLLAMA_TIMEOUT_MS);
  try {
    const res = await fetch(`${process.env.OLLAMA_URL ?? DEFAULT_OLLAMA_URL}/api/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        model,
        messages: buildMessages(files),
        stream: false,
        format: "json",
        options: { temperature: 0 },
      }),
      cache: "no-store",
      signal: controller.signal,
    });
    const body = await res.json().catch(() => ({}));
    if (!res.ok) {
      // e.g. 404 "model not found" when the model was never pulled
      return { status: 503, error: `Ollama error: ${body.error ?? res.status} (try \`ollama pull ${model}\`)` };
    }
    return { content: body.message?.content ?? "", model: body.model ?? model };
  } catch {
    if (controller.signal.aborted) {
      return { status: 504, error: `the local model did not answer within ${OLLAMA_TIMEOUT_MS / 1000}s` };
    }
    return { status: 503, error: "Ollama not running – start it with `ollama serve`" };
  } finally {
    clearTimeout(timeout);
  }
}

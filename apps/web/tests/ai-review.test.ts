import { afterEach, describe, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";
import { verifyFindings } from "../lib/ai-review";
import { GET } from "../app/api/demo/ai-review/route";

const SOURCE = [
  "function cartTotal(items) {",
  "  let total = 0;",
  "  for (let i = 0; i <= items.length; i++) {",
  "    total += items[i].price;",
  "  }",
  "  return total;",
  "}",
].join("\n");
const FILES = [{ filename: "logic_sample.js", source: SOURCE }];

const realFinding = {
  file: "logic_sample.js",
  start_line: 99, // wrong on purpose: lines are taken from where the quote is found
  end_line: 99,
  severity: "high",
  title: "Off-by-one in loop bound",
  explanation: "i <= items.length reads one past the end.",
  quote: "for (let i = 0; i <= items.length; i++) {",
};
const hallucinatedFinding = { ...realFinding, title: "Invented", quote: "if (items == null) return 0;" };

describe("AI arm quote verification", () => {
  it("keeps a finding whose quote is real code and anchors it to the quoted line", () => {
    const out = verifyFindings(JSON.stringify({ findings: [realFinding] }), FILES);
    expect(out.discarded_count).toBe(0);
    expect(out.findings).toHaveLength(1);
    expect(out.findings[0]).toMatchObject({ title: "Off-by-one in loop bound", start_line: 3, end_line: 3 });
  });

  it("drops a finding whose quote does not appear in the file, and counts it", () => {
    const out = verifyFindings(JSON.stringify({ findings: [realFinding, hallucinatedFinding] }), FILES);
    expect(out.findings.map((f) => f.title)).toEqual(["Off-by-one in loop bound"]);
    expect(out.discarded_count).toBe(1);
  });

  it("turns malformed model JSON into zero findings plus an error note, without throwing", () => {
    const out = verifyFindings("{not json", FILES);
    expect(out.findings).toEqual([]);
    expect(out.error).toMatch(/malformed JSON/);
  });
});

describe("GET /api/demo/ai-review", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  const request = () => new NextRequest("http://localhost/api/demo/ai-review?fixture=logic");

  it("sends the fixture to Ollama and returns only verified findings", async () => {
    const fetchMock = vi.fn(async (url: string) => {
      if (url.endsWith("/demo/fixtures")) {
        return { ok: true, json: async () => ({ fixtures: [{ id: "logic_sample", ...FILES[0] }] }) };
      }
      const content = JSON.stringify({ findings: [realFinding, hallucinatedFinding] });
      return { ok: true, json: async () => ({ model: "qwen2.5-coder:7b", message: { content } }) };
    });
    vi.stubGlobal("fetch", fetchMock);

    const response = await GET(request());
    const body = await response.json();

    expect(response.status).toBe(200);
    expect(body.findings).toHaveLength(1);
    expect(body.discarded_count).toBe(1);
    expect(body.model).toBe("qwen2.5-coder:7b");

    const sent = JSON.parse((fetchMock.mock.calls[1] as unknown as [string, { body: string }])[1].body);
    expect(sent).toMatchObject({ stream: false, format: "json", options: { temperature: 0 } });
    expect(sent.messages[1].content).toContain('<file name="logic_sample.js">');
  });

  it("returns a clear 503 when Ollama is not running", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string) => {
        if (url.endsWith("/demo/fixtures")) {
          return { ok: true, json: async () => ({ fixtures: [FILES[0]] }) };
        }
        throw new Error("connect ECONNREFUSED 127.0.0.1:11434");
      }),
    );

    const response = await GET(request());
    expect(response.status).toBe(503);
    expect((await response.json()).error).toMatch(/ollama serve/);
  });
});

import { describe, expect, it } from "vitest";
import {
  advanceResearchRunStep,
  api,
  cancelResearchRun,
  createHypothesis,
  executeExperiment,
  getResearchRun,
  listResearchRuns,
  recoverWorkflow,
  resumeResearchRun,
  retryResearchRunStep,
  startResearchRun,
  streamWorkflowOperationsEvents,
  transitionHypothesis,
} from "./api";

describe("API client", () => {
  it("sends a content type and safely handles a non-Electron test runtime", async () => {
    let headers: Headers | undefined;
    globalThis.fetch = (async (_url, init) => {
      headers = new Headers(init?.headers);
      return new Response("{}", {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    }) as typeof fetch;
    await api("/api/health");
    expect(headers?.get("Content-Type")).toBe("application/json");
    expect(headers?.get("X-Vibe-Session-Token")).toBe("");
  });

  it("sends every falsifiable hypothesis field and an auditable reason", async () => {
    let request: { url: string; body: Record<string, unknown> } | undefined;
    globalThis.fetch = (async (url, init) => {
      request = {
        url: String(url),
        body: JSON.parse(String(init?.body)),
      };
      return new Response(
        JSON.stringify({ hypotheses: [], hypothesis_readiness: {} }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      );
    }) as typeof fetch;
    await createHypothesis(
      "项目 α",
      {
        statement: "H1",
        mechanism: "M",
        prediction: "P",
        falsification_criteria: "F",
        boundary_conditions: "B",
      },
      "preregister",
    );
    expect(request?.url).toContain(
      "/api/research-projects/项目 α/hypotheses",
    );
    expect(request?.body).toMatchObject({
      statement: "H1",
      mechanism: "M",
      prediction: "P",
      falsification_criteria: "F",
      boundary_conditions: "B",
      actor: "researcher",
      change_reason: "preregister",
    });
  });

  it("binds a confirmatory experiment to an explicit frozen version", async () => {
    const calls: Array<{ url: string; body: Record<string, unknown> }> = [];
    globalThis.fetch = (async (url, init) => {
      calls.push({ url: String(url), body: JSON.parse(String(init?.body)) });
      return new Response("{}", {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    }) as typeof fetch;
    await transitionHypothesis("project-1", "version-1", "freeze", "locked");
    await executeExperiment(
      "project-1",
      [1, 2],
      [2, 3],
      3,
      "outcome",
      "confirmatory",
      "version-1",
    );
    expect(calls[0]).toEqual({
      url: "/api/research-projects/project-1/hypotheses/version-1/freeze",
      body: { actor: "researcher", reason: "locked" },
    });
    expect(calls[1].body).toMatchObject({
      analysis_mode: "confirmatory",
      hypothesis_version_id: "version-1",
      control: [1, 2],
      treatment: [2, 3],
    });
  });

  it("submits an auditable recovery command instead of mutating status locally", async () => {
    let request: { url: string; method?: string; body: Record<string, unknown> } | undefined;
    globalThis.fetch = (async (url, init) => {
      request = {
        url: String(url),
        method: init?.method,
        body: JSON.parse(String(init?.body)),
      };
      return new Response(
        JSON.stringify({
          ok: true,
          operation_id: "recovery-1",
          workflow_id: "workflow-博士生",
          skill_name: "paper-plan",
          status: "accepted",
        }),
        { status: 202, headers: { "Content-Type": "application/json" } },
      );
    }) as typeof fetch;
    await recoverWorkflow("workflow-博士生", "研究者确认失败原因已经消除");
    expect(request).toEqual({
      url: "/api/workflows/workflow-%E5%8D%9A%E5%A3%AB%E7%94%9F/recover",
      method: "POST",
      body: {
        reason: "研究者确认失败原因已经消除",
        requested_by: "researcher",
      },
    });
  });

  it("decodes durable workflow SSE events and exposes the connected state", async () => {
    const encoder = new TextEncoder();
    const payload = [
      "id: 41",
      "event: step_failed",
      'data: {"workflow_id":"wf-1","payload":{"step":"paper-plan","error":"provider failed"}}',
      "",
      "",
    ].join("\n");
    globalThis.fetch = (async () =>
      new Response(
        new ReadableStream({
          start(controller) {
            controller.enqueue(encoder.encode(payload));
            controller.close();
          },
        }),
        { status: 200, headers: { "Content-Type": "text/event-stream" } },
      )) as typeof fetch;
    const events: Array<{ id: number; event: string }> = [];
    await streamWorkflowOperationsEvents(
      {},
      (event) => events.push({ id: event.id, event: event.event }),
      new AbortController().signal,
    );
    expect(events).toEqual([
      { id: 0, event: "heartbeat" },
      { id: 41, event: "step_failed" },
    ]);
  });

  it("wires research-run lifecycle to non-forgeable gate endpoints", async () => {
    const calls: Array<{ url: string; method?: string; body?: Record<string, unknown> }> = [];
    globalThis.fetch = (async (url, init) => {
      const method = init?.method || "GET";
      const entry: { url: string; method?: string; body?: Record<string, unknown> } = {
        url: String(url),
        method,
      };
      if (init?.body) entry.body = JSON.parse(String(init.body));
      calls.push(entry);
      return new Response(
        JSON.stringify({
          id: "run-1",
          project_id: "project-α",
          status: "paused",
          current_step: "contract",
          steps: [{ name: "contract", status: "pending" }],
        }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      );
    }) as typeof fetch;

    await startResearchRun("project-α");
    await listResearchRuns("project-α");
    await getResearchRun("run-1");
    await advanceResearchRunStep("run-1", "contract", {
      input: { source: "workbench" },
      artifacts: [{ id: "art-1" }],
      provenance: [{ source: "hypothesis:manifest" }],
      gate_passed: true,
      failure_reason: null,
    });
    await retryResearchRunStep("run-1", "contract");
    await resumeResearchRun("run-1");
    await cancelResearchRun("run-1", "user cancel");

    expect(calls.map((item) => `${item.method} ${item.url}`)).toEqual([
      "POST /api/research-runs/projects/project-α",
      "GET /api/research-runs/projects/project-α",
      "GET /api/research-runs/run-1",
      "POST /api/research-runs/run-1/steps/contract",
      "POST /api/research-runs/run-1/steps/contract/retry",
      "POST /api/research-runs/run-1/resume",
      "POST /api/research-runs/run-1/cancel",
    ]);
    expect(calls[3].body).toMatchObject({
      gate_passed: true,
      artifacts: [{ id: "art-1" }],
      provenance: [{ source: "hypothesis:manifest" }],
    });
    expect(calls[6].body).toEqual({ reason: "user cancel" });
  });
});

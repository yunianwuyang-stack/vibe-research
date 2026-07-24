import { describe, expect, it } from "vitest";
import { buildCockpitModel } from "./cockpit";
import { FEATURE_ROUTES, ROUTE_LABELS, routeFromLocation, STATUS_REPAIR } from "./feature-routes";
import { WORKSPACE_STATUSES, normalizeWorkspaceStatus, STATUS_LABEL } from "./status";

describe("P9.0 research cockpit model", () => {
  it("asks for project when none selected", () => {
    const model = buildCockpitModel({ connected: true });
    expect(model.nextActionTarget).toBe("projects");
    expect(model.blockers.some((b) => b.id === "no-project")).toBe(true);
    expect(model.projectTitle).toBe("未选择项目");
  });

  it("prioritizes evidence when project has no cards", () => {
    const model = buildCockpitModel({
      connected: true,
      project: {
        id: "p1",
        title: "Demo",
        status: "running",
        evidence_cards: [],
        hypotheses: [],
      },
    });
    expect(model.nextActionTarget).toBe("evidence");
    expect(model.evidenceCoveragePercent).toBe(0);
  });

  it("reports coverage and manuscript produced state", () => {
    const model = buildCockpitModel({
      connected: true,
      project: {
        id: "p1",
        title: "Demo",
        status: "approved",
        evidence_cards: [
          { citation_status: "approved", claim_support_status: "approved" },
          { citation_status: "approved", claim_support_status: "approved" },
        ],
        hypotheses: [{ is_current: true, status: "frozen" }],
      },
      workflows: [{ id: "w1", title: "run-a", status: "completed" }],
      draftText: "x".repeat(600),
      draftHash: "abc",
    });
    expect(model.evidenceVerified).toBe(2);
    expect(model.evidenceTotal).toBe(2);
    expect(model.evidenceCoveragePercent).toBe(100);
    expect(model.manuscriptStatus).toBe("produced");
    expect(model.recentRuns[0]?.status).toBe("produced");
    expect(model.nextActionTarget).toBe("claims");
  });

  it("surfaces offline backend as blocker with repair", () => {
    const model = buildCockpitModel({ connected: false });
    const offline = model.blockers.find((b) => b.id === "backend-offline");
    expect(offline?.repair).toMatch(/后端/);
    expect(offline?.target).toBe("settings");
  });
});

describe("P9 status vocabulary", () => {
  it("covers all eight statuses with labels and repairs", () => {
    expect(WORKSPACE_STATUSES).toHaveLength(8);
    for (const status of WORKSPACE_STATUSES) {
      expect(STATUS_LABEL[status]).toBeTruthy();
      expect(STATUS_REPAIR[status]).toBeTruthy();
    }
    expect(normalizeWorkspaceStatus("needs_review")).toBe("verifying");
    expect(normalizeWorkspaceStatus("approved")).toBe("accepted");
    expect(normalizeWorkspaceStatus("failed")).toBe("failed");
  });
});

describe("P9 feature routes", () => {
  it("exposes eight PhD routes with labels", () => {
    expect(FEATURE_ROUTES).toHaveLength(8);
    for (const route of FEATURE_ROUTES) {
      expect(ROUTE_LABELS[route]).toBeTruthy();
    }
    expect(ROUTE_LABELS.dashboard).toContain("驾驶舱");
  });

  it("restores routes and falls back to dashboard", () => {
    expect(routeFromLocation("/evidence")).toBe("evidence");
    expect(routeFromLocation("/research-map/")).toBe("research-map");
    expect(routeFromLocation("/unknown")).toBe("dashboard");
  });
});

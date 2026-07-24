import { describe, expect, it } from "vitest";
import {
  FEATURE_ROUTES,
  ROUTE_LABELS,
  STATUS_REPAIR,
  routeFromLocation,
} from "./feature-routes";
import { WORKSPACE_STATUSES } from "./status";

describe("P9 feature route contract", () => {
  it("supports direct route restoration and safe fallback", () => {
    expect(routeFromLocation("/evidence")).toBe("evidence");
    expect(routeFromLocation("/runs/")).toBe("runs");
    expect(routeFromLocation("/unknown")).toBe("dashboard");
    expect(FEATURE_ROUTES).toHaveLength(8);
  });

  it("requires a recovery action for every terminal status", () => {
    for (const status of ["blocked", "stale", "failed"] as const) {
      expect(STATUS_REPAIR[status]).toBeTruthy();
    }
    for (const status of WORKSPACE_STATUSES) {
      expect(STATUS_REPAIR[status].length).toBeGreaterThan(0);
    }
  });

  it("labels all feature routes in Chinese for PhD cockpit", () => {
    expect(ROUTE_LABELS.dashboard).toBe("研究驾驶舱");
    expect(ROUTE_LABELS["research-map"]).toBe("研究地图");
    expect(Object.keys(ROUTE_LABELS)).toContain("claims");
  });
});

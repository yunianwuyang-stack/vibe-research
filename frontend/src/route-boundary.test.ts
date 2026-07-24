import { describe, expect, it } from "vitest";
import { FEATURE_ROUTES } from "./feature-routes";
import {
  ROUTE_TO_PAGE,
  PAGE_TO_ROUTE,
  assertFeatureRouteCoverage,
  featureRouteForPage,
  pageFromFeatureRoute,
} from "./route-boundary";

describe("P9.1 route boundary", () => {
  it("maps every feature route to a distinct shell page", () => {
    const coverage = assertFeatureRouteCoverage();
    expect(coverage.ok).toBe(true);
    const pages = FEATURE_ROUTES.map((route) => ROUTE_TO_PAGE[route]);
    expect(new Set(pages).size).toBe(FEATURE_ROUTES.length);
    expect(ROUTE_TO_PAGE["research-map"]).toBe("研究地图");
    expect(pageFromFeatureRoute("research-map")).toBe("研究地图");
    expect(featureRouteForPage("研究地图")).toBe("research-map");
  });

  it("round-trips primary feature pages", () => {
    for (const route of FEATURE_ROUTES) {
      const page = pageFromFeatureRoute(route);
      expect(PAGE_TO_ROUTE[page]).toBe(route);
    }
    expect(pageFromFeatureRoute("dashboard")).toBe("工作台");
  });
});

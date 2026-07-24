/** P9 feature route contract + status repair re-exports. */
import {
  STATUS_REPAIR as STATUS_REPAIR_FROM_STATUS,
  type WorkspaceStatus,
} from "./status";

export type FeatureRoute =
  | "projects"
  | "research-map"
  | "evidence"
  | "experiments"
  | "claims"
  | "manuscript"
  | "runs"
  | "settings";

export const FEATURE_ROUTES: readonly FeatureRoute[] = [
  "projects",
  "research-map",
  "evidence",
  "experiments",
  "claims",
  "manuscript",
  "runs",
  "settings",
] as const;

/** PhD-facing labels (zh) for the 8 feature routes + dashboard. */
export const ROUTE_LABELS: Record<FeatureRoute | "dashboard", string> = {
  dashboard: "研究驾驶舱",
  projects: "研究项目",
  "research-map": "研究地图",
  evidence: "文献与证据",
  experiments: "实验与复现",
  claims: "主张与门禁",
  manuscript: "科学写作",
  runs: "运行与产物",
  settings: "设置",
};

export type { WorkspaceStatus };
export const STATUS_REPAIR: Record<WorkspaceStatus, string> = {
  ...STATUS_REPAIR_FROM_STATUS,
};

export function routeFromLocation(
  pathname = typeof window !== "undefined" ? window.location.pathname : "/",
): FeatureRoute | "dashboard" {
  const route = pathname.replace(/^\/+|\/+$/g, "");
  return route && FEATURE_ROUTES.includes(route as FeatureRoute)
    ? (route as FeatureRoute)
    : "dashboard";
}

export function navigateToRoute(route: FeatureRoute | "dashboard") {
  if (typeof window === "undefined") return;
  window.history.pushState(
    { route },
    "",
    route === "dashboard" ? "/" : `/${route}`,
  );
}

export function isFeatureRoute(value: string): value is FeatureRoute {
  return FEATURE_ROUTES.includes(value as FeatureRoute);
}

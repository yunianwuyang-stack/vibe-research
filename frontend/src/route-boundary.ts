/** P9.1 feature route ↔ legacy page boundary (single source). */
import {
  FEATURE_ROUTES,
  type FeatureRoute,
} from "./feature-routes";

/** Legacy shell page ids still used by main.tsx strangler. */
export type ShellPage =
  | "工作台"
  | "研究项目"
  | "研究地图"
  | "智能工作流"
  | "全局运营台"
  | "执行与产物"
  | "编辑与编译"
  | "文献与证据"
  | "筛选协议"
  | "实验与复现"
  | "科学写作"
  | "审批与审计"
  | "设置与连接";

export const FEATURE_SHELL_PAGES: readonly ShellPage[] = [
  "研究项目",
  "研究地图",
  "文献与证据",
  "实验与复现",
  "审批与审计",
  "科学写作",
  "执行与产物",
  "设置与连接",
] as const;

/** Canonical mapping from P9 feature routes to shell pages. */
export const ROUTE_TO_PAGE: Record<FeatureRoute | "dashboard", ShellPage> = {
  dashboard: "工作台",
  projects: "研究项目",
  "research-map": "研究地图",
  evidence: "文献与证据",
  experiments: "实验与复现",
  claims: "审批与审计",
  manuscript: "科学写作",
  runs: "执行与产物",
  settings: "设置与连接",
};

/** Inverse map for primary feature pages (workbench → dashboard). */
export const PAGE_TO_ROUTE: Partial<Record<ShellPage, FeatureRoute | "dashboard">> = {
  工作台: "dashboard",
  研究项目: "projects",
  研究地图: "research-map",
  文献与证据: "evidence",
  实验与复现: "experiments",
  审批与审计: "claims",
  科学写作: "manuscript",
  执行与产物: "runs",
  设置与连接: "settings",
};

export function pageFromFeatureRoute(route: FeatureRoute | "dashboard"): ShellPage {
  return ROUTE_TO_PAGE[route] || "工作台";
}

export function featureRouteForPage(page: ShellPage): FeatureRoute | "dashboard" {
  return PAGE_TO_ROUTE[page] || "dashboard";
}

export function isFeatureShellPage(page: string): page is ShellPage {
  return page in PAGE_TO_ROUTE || page === "工作台";
}

export function assertFeatureRouteCoverage(): {
  ok: boolean;
  missing: string[];
} {
  const missing: string[] = [];
  for (const route of FEATURE_ROUTES) {
    if (!ROUTE_TO_PAGE[route]) missing.push(route);
  }
  if (!ROUTE_TO_PAGE.dashboard) missing.push("dashboard");
  return { ok: missing.length === 0, missing };
}

/**
 * P9.0 Research Cockpit — first screen for PhD workflow.
 * Project · next action · blockers · evidence coverage · recent runs · manuscript.
 */
import React from "react";
import {
  FEATURE_ROUTES,
  ROUTE_LABELS,
  type FeatureRoute,
} from "./feature-routes";
import {
  STATUS_LABEL,
  STATUS_REPAIR,
  normalizeWorkspaceStatus,
  type WorkspaceStatus,
} from "./status";

export type CockpitProject = {
  id: string;
  title: string;
  status?: string;
  research_question?: string;
  evidence_cards?: Array<{
    citation_status?: string;
    claim_support_status?: string;
  }>;
  hypotheses?: Array<{ is_current?: boolean; status?: string }>;
};

export type CockpitRun = {
  id: string;
  title?: string;
  status?: string;
  current_step?: string | null;
  updated_at?: string;
  created_at?: string;
};

export type CockpitNavTarget =
  | FeatureRoute
  | "dashboard"
  | "projects"
  | "evidence"
  | "experiments"
  | "claims"
  | "manuscript"
  | "runs"
  | "settings"
  | "research-map";

export type CockpitModel = {
  projectTitle: string;
  projectStatus: WorkspaceStatus;
  projectStatusLabel: string;
  nextActionLabel: string;
  nextActionTarget: CockpitNavTarget;
  nextActionRepair: string;
  blockers: Array<{ id: string; reason: string; repair: string; target: CockpitNavTarget }>;
  evidenceTotal: number;
  evidenceVerified: number;
  evidenceCoveragePercent: number;
  recentRuns: Array<{
    id: string;
    title: string;
    status: WorkspaceStatus;
    statusLabel: string;
    repair: string;
    step?: string;
  }>;
  manuscriptStatus: WorkspaceStatus;
  manuscriptLabel: string;
  manuscriptRepair: string;
  connected: boolean;
};

export function buildCockpitModel(input: {
  connected: boolean;
  project?: CockpitProject | null;
  workflows?: CockpitRun[];
  researchRuns?: CockpitRun[];
  draftText?: string;
  draftHash?: string;
}): CockpitModel {
  const project = input.project || null;
  const evidenceCards = project?.evidence_cards || [];
  const evidenceVerified = evidenceCards.filter(
    (item) =>
      item.citation_status === "approved" &&
      item.claim_support_status === "approved",
  ).length;
  const evidenceTotal = evidenceCards.length;
  const evidenceCoveragePercent = evidenceTotal
    ? Math.round((evidenceVerified / evidenceTotal) * 100)
    : 0;

  const currentHypotheses = (project?.hypotheses || []).filter((h) => h.is_current);
  const frozenHypotheses = currentHypotheses.filter((h) => h.status === "frozen");
  const draftText = (input.draftText || "").trim();
  const hasDraft = Boolean(draftText || input.draftHash);

  const blockers: CockpitModel["blockers"] = [];
  if (!input.connected) {
    blockers.push({
      id: "backend-offline",
      reason: "本地后端未连接",
      repair: "检查桌面后端进程并重试连接",
      target: "settings",
    });
  }
  if (!project) {
    blockers.push({
      id: "no-project",
      reason: "尚未选择或建立研究项目",
      repair: "建立研究合同或选择已有项目",
      target: "projects",
    });
  } else {
    const projectStatus = normalizeWorkspaceStatus(project.status);
    if (projectStatus === "blocked" || projectStatus === "failed" || projectStatus === "stale") {
      blockers.push({
        id: "project-status",
        reason: `项目状态为${STATUS_LABEL[projectStatus]}`,
        repair: STATUS_REPAIR[projectStatus],
        target: "claims",
      });
    }
    if (evidenceTotal === 0) {
      blockers.push({
        id: "no-evidence",
        reason: "尚无证据卡",
        repair: "检索文献并保存证据卡",
        target: "evidence",
      });
    } else if (evidenceVerified < evidenceTotal) {
      blockers.push({
        id: "evidence-unverified",
        reason: `${evidenceTotal - evidenceVerified} 条证据待核验`,
        repair: STATUS_REPAIR.verifying,
        target: "evidence",
      });
    }
    if (currentHypotheses.length === 0) {
      blockers.push({
        id: "no-hypothesis",
        reason: "尚无当前假设",
        repair: "在研究地图中写入可证伪假设",
        target: "research-map",
      });
    } else if (frozenHypotheses.length === 0) {
      blockers.push({
        id: "hypothesis-unfrozen",
        reason: "假设尚未冻结",
        repair: "审阅并冻结假设后进入实验",
        target: "research-map",
      });
    }
  }

  let nextActionLabel = "打开研究项目";
  let nextActionTarget: CockpitNavTarget = "projects";
  if (!project) {
    nextActionLabel = "建立或选择研究项目";
    nextActionTarget = "projects";
  } else if (evidenceTotal === 0) {
    nextActionLabel = "补充文献与证据";
    nextActionTarget = "evidence";
  } else if (evidenceVerified < evidenceTotal) {
    nextActionLabel = "核验证据卡";
    nextActionTarget = "evidence";
  } else if (currentHypotheses.length === 0 || frozenHypotheses.length === 0) {
    nextActionLabel = "完善研究地图与假设";
    nextActionTarget = "research-map";
  } else if (!(input.researchRuns?.length || input.workflows?.length)) {
    nextActionLabel = "启动实验或研究运行";
    nextActionTarget = "experiments";
  } else if (!hasDraft) {
    nextActionLabel = "撰写稿件草稿";
    nextActionTarget = "manuscript";
  } else {
    nextActionLabel = "继续主张绑定与门禁";
    nextActionTarget = "claims";
  }

  const projectStatus = normalizeWorkspaceStatus(project?.status);
  const mergedRuns: CockpitRun[] = [
    ...(input.researchRuns || []).map((run) => ({
      ...run,
      title: run.title || `研究运行 ${run.id.slice(0, 8)}`,
    })),
    ...(input.workflows || []).map((run) => ({
      ...run,
      title: run.title || `工作流 ${run.id.slice(0, 8)}`,
    })),
  ]
    .sort((a, b) => {
      const ta = Date.parse(a.updated_at || a.created_at || "") || 0;
      const tb = Date.parse(b.updated_at || b.created_at || "") || 0;
      return tb - ta;
    })
    .slice(0, 5);

  const recentRuns = mergedRuns.map((run) => {
    const status = normalizeWorkspaceStatus(run.status);
    return {
      id: run.id,
      title: run.title || run.id,
      status,
      statusLabel: STATUS_LABEL[status],
      repair: STATUS_REPAIR[status],
      step: run.current_step || undefined,
    };
  });

  let manuscriptStatus: WorkspaceStatus = "queued";
  if (hasDraft) {
    manuscriptStatus = draftText.length > 500 ? "produced" : "verifying";
  }
  if (!project) manuscriptStatus = "blocked";

  return {
    projectTitle: project?.title || "未选择项目",
    projectStatus,
    projectStatusLabel: project ? STATUS_LABEL[projectStatus] : "未建立",
    nextActionLabel,
    nextActionTarget,
    nextActionRepair: STATUS_REPAIR[projectStatus] || STATUS_REPAIR.queued,
    blockers,
    evidenceTotal,
    evidenceVerified,
    evidenceCoveragePercent,
    recentRuns,
    manuscriptStatus,
    manuscriptLabel: STATUS_LABEL[manuscriptStatus],
    manuscriptRepair: STATUS_REPAIR[manuscriptStatus],
    connected: input.connected,
  };
}

export function ResearchCockpit({
  connected,
  project,
  workflows = [],
  researchRuns = [],
  draftText = "",
  draftHash = "",
  onNavigate,
}: {
  connected: boolean;
  project?: CockpitProject | null;
  workflows?: CockpitRun[];
  researchRuns?: CockpitRun[];
  draftText?: string;
  draftHash?: string;
  onNavigate: (target: CockpitNavTarget) => void;
}) {
  const model = buildCockpitModel({
    connected,
    project,
    workflows,
    researchRuns,
    draftText,
    draftHash,
  });

  return (
    <section className="research-cockpit" aria-label="研究驾驶舱">
      <header className="cockpit-header">
        <div>
          <p className="eyebrow">Research Cockpit</p>
          <h1>研究驾驶舱</h1>
          <p className="cockpit-sub">
            项目、下一动作、阻断、证据覆盖、最近运行与稿件状态 — 一次看清。
          </p>
        </div>
        <div className="cockpit-connection" role="status">
          <span className={`live-dot ${model.connected ? "on" : "off"}`} aria-hidden="true" />
          <span>{model.connected ? "本地后端已连接" : "后端未连接"}</span>
        </div>
      </header>

      <div className="cockpit-grid">
        <article className="cockpit-card cockpit-project">
          <header>
            <h2>当前项目</h2>
            <span className={`status-chip status-${model.projectStatus}`}>
              {model.projectStatusLabel}
            </span>
          </header>
          <p className="cockpit-project-title">{model.projectTitle}</p>
          {project?.research_question ? (
            <p className="cockpit-muted">{project.research_question}</p>
          ) : (
            <p className="cockpit-muted">尚未写入研究问题</p>
          )}
          <button type="button" className="quiet compact-action" onClick={() => onNavigate("projects")}>
            管理项目
          </button>
        </article>

        <article className="cockpit-card cockpit-next">
          <header>
            <h2>下一研究动作</h2>
          </header>
          <p className="cockpit-next-label">{model.nextActionLabel}</p>
          <p className="cockpit-muted">{model.nextActionRepair}</p>
          <button type="button" onClick={() => onNavigate(model.nextActionTarget)}>
            执行下一动作
          </button>
        </article>

        <article className="cockpit-card cockpit-blockers">
          <header>
            <h2>阻断</h2>
            <span className="cockpit-count">{model.blockers.length}</span>
          </header>
          {model.blockers.length === 0 ? (
            <p className="cockpit-muted">当前无阻断</p>
          ) : (
            <ul className="cockpit-blocker-list">
              {model.blockers.map((item) => (
                <li key={item.id}>
                  <div>
                    <b>{item.reason}</b>
                    <small>{item.repair}</small>
                  </div>
                  <button
                    type="button"
                    className="quiet compact-action"
                    onClick={() => onNavigate(item.target)}
                  >
                    修复
                  </button>
                </li>
              ))}
            </ul>
          )}
        </article>

        <article className="cockpit-card cockpit-evidence">
          <header>
            <h2>证据覆盖</h2>
            <span className="cockpit-count">{model.evidenceCoveragePercent}%</span>
          </header>
          <p>
            已核验 <b>{model.evidenceVerified}</b> / 总计 <b>{model.evidenceTotal}</b>
          </p>
          <div
            className="cockpit-meter"
            role="meter"
            aria-valuemin={0}
            aria-valuemax={100}
            aria-valuenow={model.evidenceCoveragePercent}
            aria-label="证据覆盖率"
          >
            <span style={{ width: `${model.evidenceCoveragePercent}%` }} />
          </div>
          <button type="button" className="quiet compact-action" onClick={() => onNavigate("evidence")}>
            打开证据
          </button>
        </article>

        <article className="cockpit-card cockpit-runs">
          <header>
            <h2>最近运行</h2>
            <button type="button" className="quiet compact-action" onClick={() => onNavigate("runs")}>
              全部运行
            </button>
          </header>
          {model.recentRuns.length === 0 ? (
            <p className="cockpit-muted">尚无运行记录</p>
          ) : (
            <ul className="cockpit-run-list">
              {model.recentRuns.map((run) => (
                <li key={run.id}>
                  <div>
                    <b>{run.title}</b>
                    <small>
                      {run.step || "—"} · {run.repair}
                    </small>
                  </div>
                  <span className={`status-chip status-${run.status}`}>{run.statusLabel}</span>
                </li>
              ))}
            </ul>
          )}
        </article>

        <article className="cockpit-card cockpit-manuscript">
          <header>
            <h2>稿件状态</h2>
            <span className={`status-chip status-${model.manuscriptStatus}`}>
              {model.manuscriptLabel}
            </span>
          </header>
          <p className="cockpit-muted">{model.manuscriptRepair}</p>
          <button type="button" className="quiet compact-action" onClick={() => onNavigate("manuscript")}>
            打开稿件
          </button>
        </article>
      </div>

      <nav className="cockpit-feature-nav" aria-label="功能路由">
        {FEATURE_ROUTES.map((route) => (
          <button key={route} type="button" className="quiet" onClick={() => onNavigate(route)}>
            {ROUTE_LABELS[route]}
          </button>
        ))}
      </nav>
    </section>
  );
}

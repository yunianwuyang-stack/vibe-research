/**
 * P9.1 Research Map feature page.
 * Question → tension → mechanism → hypotheses → claims → boundaries.
 */
import React from "react";
import type { NarrativeMap, Project } from "./api";
import { Panel, Field, Empty } from "./ui";
import { STATUS_LABEL, normalizeWorkspaceStatus } from "./status";

export type ResearchMapHypothesis = {
  id?: string;
  hypothesis_id?: string;
  version?: number;
  statement?: string;
  status?: string;
  is_current?: boolean;
};

export type ResearchMapProps = {
  busy: boolean;
  project?: Project | null;
  narrative: NarrativeMap;
  frozenHypotheses: ResearchMapHypothesis[];
  onNarrativeChange: (next: NarrativeMap) => void;
  onSave: () => void;
  onApprove: () => void;
  onOpenProjects: () => void;
  onOpenManuscript: () => void;
};

export function researchMapReadiness(input: {
  project?: Project | null;
  narrative: NarrativeMap;
  frozenCount: number;
}): {
  status: ReturnType<typeof normalizeWorkspaceStatus>;
  blockers: string[];
  canSave: boolean;
  canApprove: boolean;
} {
  const blockers: string[] = [];
  if (!input.project) blockers.push("尚未选择研究项目");
  if (!input.narrative.tension.trim()) blockers.push("缺少文献张力");
  if (!input.narrative.mechanism.trim()) blockers.push("缺少候选机制");
  if (input.frozenCount === 0) blockers.push("尚无冻结假设");
  if (!(input.narrative.claims[0] || "").trim()) blockers.push("缺少主张 ID");
  if (!(input.narrative.competing_explanations[0] || "").trim())
    blockers.push("缺少替代解释");
  const canSave = Boolean(input.project) && input.frozenCount > 0;
  const canApprove = Boolean(input.project) && !input.narrative.approved;
  const status = !input.project
    ? normalizeWorkspaceStatus("blocked")
    : input.narrative.approved
      ? normalizeWorkspaceStatus("accepted")
      : blockers.length
        ? normalizeWorkspaceStatus("blocked")
        : normalizeWorkspaceStatus("verifying");
  return { status, blockers, canSave, canApprove };
}

export function ResearchMapPage({
  busy,
  project,
  narrative,
  frozenHypotheses,
  onNarrativeChange,
  onSave,
  onApprove,
  onOpenProjects,
  onOpenManuscript,
}: ResearchMapProps) {
  const readiness = researchMapReadiness({
    project,
    narrative,
    frozenCount: frozenHypotheses.length,
  });
  const setField = <K extends keyof NarrativeMap>(key: K, value: NarrativeMap[K]) => {
    onNarrativeChange({ ...narrative, [key]: value });
  };

  return (
    <Panel
      title="研究地图"
      detail="把研究问题、文献张力、机制、冻结假设、主张与边界放在同一张可审计的论证地图上。"
    >
      <div className="research-map" aria-label="研究地图">
        <header className="research-map-status">
          <div>
            <p className="eyebrow">Research Map</p>
            <h2>{project?.title || "未选择项目"}</h2>
          </div>
          <span className={`status-chip status-${readiness.status}`}>
            {STATUS_LABEL[readiness.status]}
          </span>
        </header>

        {!project ? (
          <Empty text="先建立或选择研究项目，再编辑研究地图。" />
        ) : (
          <>
            <section className="research-map-question" aria-label="研究问题">
              <h3>研究问题</h3>
              <p>{project.research_question || narrative.question || "（项目尚未写入研究问题）"}</p>
            </section>

            <div className="form-grid">
              <Field
                label="文献张力"
                value={narrative.tension}
                set={(value) => setField("tension", value)}
                area
                placeholder="既有研究在哪些发现或解释上冲突？"
              />
              <Field
                label="候选机制"
                value={narrative.mechanism}
                set={(value) => setField("mechanism", value)}
                area
                placeholder="提出可检验的机制"
              />
              <label className="wide">
                当前冻结假设（由注册表同步）
                <textarea
                  readOnly
                  value={
                    frozenHypotheses.length
                      ? frozenHypotheses
                          .map((item) => {
                            const hid = (item.hypothesis_id || item.id || "").slice(0, 8);
                            return `H-${hid} v${item.version ?? "?"}: ${item.statement || ""}`;
                          })
                          .join("\n")
                      : "尚无冻结假设；保存论证图将被阻断。请先在研究项目中冻结假设。"
                  }
                />
              </label>
              <Field
                label="主张 ID"
                value={narrative.claims[0] || ""}
                set={(value) => setField("claims", [value])}
                placeholder="C1"
              />
              <Field
                label="替代解释"
                value={narrative.competing_explanations[0] || ""}
                set={(value) => setField("competing_explanations", [value])}
                placeholder="至少一个竞争解释"
              />
              <Field
                label="边界条件"
                value={narrative.boundaries[0] || ""}
                set={(value) => setField("boundaries", [value])}
                placeholder="适用范围"
              />
              <Field
                label="局限"
                value={narrative.limitations[0] || ""}
                set={(value) => setField("limitations", [value])}
                placeholder="已知局限"
              />
            </div>

            {readiness.blockers.length > 0 && (
              <ul className="research-map-blockers" aria-label="研究地图阻断">
                {readiness.blockers.map((item) => (
                  <li key={item}>{item}</li>
                ))}
              </ul>
            )}

            <div className="actions">
              <button
                type="button"
                disabled={busy || !readiness.canSave}
                onClick={onSave}
              >
                保存论证图
              </button>
              <button
                type="button"
                disabled={busy || !readiness.canApprove}
                onClick={onApprove}
              >
                人工批准论证图
              </button>
              <button type="button" className="quiet" onClick={onOpenProjects}>
                管理假设
              </button>
              <button type="button" className="quiet" onClick={onOpenManuscript}>
                进入科学写作
              </button>
            </div>
            {narrative.approved && (
              <p className="cockpit-muted" role="status">
                论证图已批准{narrative.approved_by ? ` · ${narrative.approved_by}` : ""}。稿件生成可消费此地图。
              </p>
            )}
          </>
        )}
      </div>
    </Panel>
  );
}

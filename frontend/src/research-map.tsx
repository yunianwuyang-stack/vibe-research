/**
 * Research Map page — guides the user through the argument structure
 * of their research in plain language before saving the narrative map.
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
  if (!input.project) blockers.push("请先选择或创建研究项目");
  if (!input.narrative.tension.trim()) blockers.push("请填写「文献争议与空白」");
  if (!input.narrative.mechanism.trim()) blockers.push("请填写「你的解释机制」");
  if (input.frozenCount === 0)
    blockers.push("项目中还没有已冻结的假设 — 请先到「研究合同」冻结假设");
  if (!(input.narrative.claims[0] || "").trim())
    blockers.push("请给核心主张填写一个编号（如 C1）");
  if (!(input.narrative.competing_explanations[0] || "").trim())
    blockers.push("请填写「替代解释」");
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
      detail="在这里整理你的论点框架、已确认假设与核心主张。保存后，主张编号可在「主张-证据图」中关联文献，论证图通过后才能生成稿件。"
    >
      <div className="research-map" aria-label="研究地图">

        {/* ── 项目标题 + 状态 ─────────────────── */}
        <header className="research-map-status">
          <div>
            <h1>{project?.title || "未选择项目"}</h1>
            {project?.research_question && (
              <p>{project.research_question}</p>
            )}
          </div>
          <span className={`status-chip status-${readiness.status}`}>
            {STATUS_LABEL[readiness.status]}
          </span>
        </header>

        {!project ? (
          <Empty text="先建立或选择研究项目，再编辑研究地图。" />
        ) : (
          <>
            <section className="rm-argument" aria-labelledby="argument-title">
              <div className="rm-section-heading">
                <div>
                  <h2 id="argument-title">你的论证</h2>
                  <p>先说明问题与解释，再为后续证据关联设定主张编号。</p>
                </div>
                <span>问题 → 解释 → 主张</span>
              </div>
              <div className="rm-argument-flow">
                <div className="rm-flow-step">
                  <Field
                    label="文献争议与空白"
                    hint="现有研究在哪里留下矛盾或未解答的问题？"
                    value={narrative.tension}
                    set={(v) => setField("tension", v)}
                    area
                    placeholder="例：现有研究对 X 因素的结论相互矛盾，且缺乏针对……的纵向追踪数据"
                  />
                </div>
                <div className="rm-flow-step">
                  <Field
                    label="你的解释机制"
                    hint="你认为什么原因或路径可以解释这个现象？"
                    value={narrative.mechanism}
                    set={(v) => setField("mechanism", v)}
                    area
                    placeholder="例：我们认为 Y 通过 Z 路径影响 X，具体表现为……"
                  />
                </div>
                <div className="rm-claim-step">
                  <p className="rm-step-label">核心主张</p>
                  <p>给这条研究结论一个编号，后续用它关联证据。</p>
                  <Field
                    label="主张编号"
                    hint="如 C1、C2"
                    value={narrative.claims[0] || ""}
                    set={(v) => setField("claims", [v])}
                    placeholder="C1"
                  />
                </div>
              </div>
            </section>

            <div className="rm-support-grid">
              <section className="rm-hypotheses" aria-labelledby="hypotheses-title">
                <div className="rm-section-heading">
                  <div>
                    <h2 id="hypotheses-title">已确认假设</h2>
                    <p>来自研究合同，已冻结，不可在此修改。</p>
                  </div>
                  <button type="button" className="quiet" onClick={onOpenProjects}>
                    管理假设
                  </button>
                </div>
                <textarea
                  className="rm-hypotheses-list"
                  readOnly
                  aria-label="已确认假设"
                  value={
                    frozenHypotheses.length
                      ? frozenHypotheses
                          .map((h) => {
                            const hid = (h.hypothesis_id || h.id || "").slice(0, 8);
                            return `H-${hid} v${h.version ?? "?"}: ${h.statement || ""}`;
                          })
                          .join("\n")
                      : "暂无已冻结的假设"
                  }
                />
              </section>

              <section className="rm-boundaries" aria-labelledby="boundaries-title">
                <div className="rm-section-heading">
                  <div>
                    <h2 id="boundaries-title">论证边界</h2>
                    <p>记录替代解释、适用范围与已知局限。</p>
                  </div>
                </div>
                <div className="rm-boundary-fields">
                  <Field
                    label="替代解释"
                    value={narrative.competing_explanations[0] || ""}
                    set={(v) => setField("competing_explanations", [v])}
                    area
                    placeholder="也可能是 Z 因素，但……"
                  />
                  <Field
                    label="适用范围"
                    value={narrative.boundaries[0] || ""}
                    set={(v) => setField("boundaries", [v])}
                    area
                    placeholder="主要适用于……，不适用于……"
                  />
                  <Field
                    label="已知局限"
                    value={narrative.limitations[0] || ""}
                    set={(v) => setField("limitations", [v])}
                    area
                    placeholder="样本量有限；未控制……变量"
                  />
                </div>
              </section>
            </div>

            {/* ── 阻断提示（全宽） ────────────────── */}
            {readiness.blockers.length > 0 && (
              <ul className="research-map-blockers" aria-label="待完成项">
                {readiness.blockers.map((item) => (
                  <li key={item}>{item}</li>
                ))}
              </ul>
            )}

            {/* ── 操作按钮 ────────────────────────── */}
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
                className="quiet"
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
                论证图已批准{narrative.approved_by ? ` · ${narrative.approved_by}` : ""}，可生成稿件。
              </p>
            )}
          </>
        )}
      </div>
    </Panel>
  );
}

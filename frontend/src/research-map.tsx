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
            {/* ── 两列主网格 ─────────────────────── */}
            <div className="rm-canvas">

              {/* 左列：论点 + 论证边界 */}
              <div className="rm-left">

                {/* Section 1: 论点框架 */}
                <section className="settings-section">
                  <div className="section-command">
                    <h3>论点框架</h3>
                  </div>
                  <p className="section-desc">说明你要解决的文献矛盾，以及你提出的解释方向。</p>
                  <div className="form-grid">
                    <Field
                      label="文献争议与空白"
                      hint="现有研究在哪里留下了矛盾或未解答的问题？"
                      value={narrative.tension}
                      set={(v) => setField("tension", v)}
                      area
                      placeholder="例：现有研究对X因素的结论相互矛盾，且缺乏针对……的纵向追踪数据"
                    />
                    <Field
                      label="你的解释机制"
                      hint="你认为什么原因或路径可以解释这个现象？"
                      value={narrative.mechanism}
                      set={(v) => setField("mechanism", v)}
                      area
                      placeholder="例：我们认为Y通过Z路径影响X，具体表现为……"
                    />
                  </div>
                </section>

                {/* Section 4: 论证边界（3列平铺） */}
                <section className="settings-section">
                  <div className="section-command">
                    <h3>论证边界</h3>
                  </div>
                  <p className="section-desc">
                    排除的替代解释、结论适用范围，以及已知不足。
                  </p>
                  <div className="form-grid rm-boundary-grid">
                    <Field
                      label="替代解释"
                      hint="你排除了哪些其他解释，为什么？"
                      value={narrative.competing_explanations[0] || ""}
                      set={(v) => setField("competing_explanations", [v])}
                      area
                      placeholder="也可能是Z因素，但……"
                    />
                    <Field
                      label="适用范围"
                      hint="结论在哪些情境下有效？"
                      value={narrative.boundaries[0] || ""}
                      set={(v) => setField("boundaries", [v])}
                      area
                      placeholder="主要适用于……，不适用于……"
                    />
                    <Field
                      label="已知局限"
                      hint="这项研究有哪些不足？"
                      value={narrative.limitations[0] || ""}
                      set={(v) => setField("limitations", [v])}
                      area
                      placeholder="样本量有限；未控制……变量"
                    />
                  </div>
                </section>

              </div>{/* /rm-left */}

              {/* 右列：假设 + 主张 */}
              <div className="rm-right">

                {/* Section 2: 已确认假设 */}
                <section className="settings-section">
                  <div className="section-command">
                    <h3>已确认假设</h3>
                  </div>
                  <p className="section-desc">
                    来自研究合同，已冻结不可修改。
                    {frozenHypotheses.length === 0 && <> 请先到「管理假设」添加并冻结。</>}
                  </p>
                  <label className="wide">
                    <textarea
                      readOnly
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
                  </label>
                </section>

                {/* Section 3: 核心主张 */}
                <section className="settings-section">
                  <div className="section-command">
                    <h3>核心主张</h3>
                  </div>
                  <p className="section-desc">
                    给核心主张起一个短编号（如 C1），后续在「主张-证据图」关联证据时会用到。
                  </p>
                  <div className="form-grid">
                    <Field
                      label="主张编号"
                      hint="如 C1、C2"
                      value={narrative.claims[0] || ""}
                      set={(v) => setField("claims", [v])}
                      placeholder="C1"
                    />
                  </div>
                </section>

              </div>{/* /rm-right */}

            </div>{/* /rm-canvas */}

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

import React, { useState, useEffect } from "react";
import {
  activateScreeningProtocol,
  exportScreeningPrisma,
  getScreening,
  recordScreeningDecision,
  saveScreeningProtocol,
  type ScreeningState,
  type Project,
} from "../api";
import { Panel, Empty, Field } from "../ui";

export function ScreeningPage({
  project,
  busy,
  onRun,
}: {
  project?: Project;
  busy: boolean;
  onRun: (action: () => Promise<void>) => Promise<void>;
}) {
  const [state, setState] = useState<ScreeningState>();
  const [title, setTitle] = useState("系统综述筛选协议"),
    [inclusion, setInclusion] = useState(""),
    [exclusion, setExclusion] = useState(""),
    [strategy, setStrategy] = useState(
      "在指定 Provider 中检索；保存的证据卡逐项由研究者筛选。",
    ),
    [reason, setReason] = useState("与已激活的纳入/排除标准一致。");
  const refresh = async () => {
    if (project) setState(await getScreening(project.id));
  };
  useEffect(() => {
    if (!project) {
      setState(undefined);
      return;
    }
    void refresh();
  }, [project?.id]);
  useEffect(() => {
    if (!state?.protocol) return;
    setTitle(state.protocol.title);
    setInclusion(state.protocol.inclusion_criteria);
    setExclusion(state.protocol.exclusion_criteria);
    setStrategy(state.protocol.source_strategy);
  }, [state?.protocol?.protocol_sha256]);
  if (!project)
    return (
      <Panel
        title="筛选协议与 PRISMA"
        detail="建立研究合同后，才能固定筛选口径并记录每一张证据卡的人工决定。"
      >
        <Empty text="请先建立研究合同。" />
      </Panel>
    );
  const protocol = state?.protocol;
  const byCard = new Map(
    (state?.decisions || []).map((item) => [item.evidence_card_id, item]),
  );
  const save = () =>
    onRun(async () =>
      setState(
        await saveScreeningProtocol(project.id, {
          title,
          inclusion_criteria: inclusion || project.inclusion_criteria,
          exclusion_criteria: exclusion,
          source_strategy: strategy,
        }),
      ),
    );
  const activate = () =>
    onRun(async () => setState(await activateScreeningProtocol(project.id)));
  const decide = (
    cardId: string,
    decision: "included" | "excluded" | "uncertain",
  ) =>
    onRun(async () =>
      setState(
        await recordScreeningDecision(project.id, cardId, decision, reason),
      ),
    );
  const exportPrisma = () =>
    onRun(async () => setState(await exportScreeningPrisma(project.id)));
  return (
    <Panel
      title="筛选协议与 PRISMA"
      detail="先固定纳入、排除和检索策略；激活后的人工决定进入追加式账本，并导出可复核的 PRISMA 流程产物。"
    >
      <section className="settings-section">
        <div className="section-command">
          <h3>筛选协议</h3>
          <button
            className="icon-button quiet"
            title="刷新筛选状态"
            aria-label="刷新筛选状态"
            disabled={busy}
            onClick={() => void onRun(refresh)}
          >
            ↻
          </button>
        </div>
        <div className="form-grid">
          <Field
            label="协议名称"
            value={title}
            set={setTitle}
            placeholder="例如：开放科学可复现性系统综述"
          />
          <Field
            label="纳入标准"
            value={inclusion || project.inclusion_criteria}
            set={setInclusion}
            area
            placeholder="研究对象、年份、语言、研究设计与可获得性"
          />
          <Field
            label="排除标准"
            value={exclusion}
            set={setExclusion}
            area
            placeholder="说明应排除的研究、重复记录与无关主题"
          />
          <Field
            label="检索与去重策略"
            value={strategy}
            set={setStrategy}
            area
            placeholder="数据源、检索式、时间范围和去重规则"
          />
        </div>
        <div className="actions">
          <button
            disabled={
              busy ||
              !title.trim() ||
              !(inclusion || project.inclusion_criteria).trim() ||
              !exclusion.trim() ||
              !strategy.trim()
            }
            onClick={save}
          >
            保存协议草案
          </button>
          <button
            className="quiet"
            disabled={busy || !protocol || protocol.status === "active"}
            onClick={activate}
          >
            激活并固定版本
          </button>
          <button
            className="quiet"
            disabled={busy || protocol?.status !== "active"}
            onClick={exportPrisma}
          >
            导出 PRISMA JSON
          </button>
        </div>
        {protocol ? (
          <div className={`graph-gate ${protocol.active ? "passed" : "blocked"}`}>
            <b>{protocol.active ? "协议已激活" : "协议草案未激活"}</b>
            <span>
              v{protocol.version} · {protocol.protocol_sha256.slice(0, 16)}
            </span>
            <code>{protocol.artifact_path}</code>
          </div>
        ) : (
          <Empty text="尚未保存筛选协议。" />
        )}
      </section>
      <section className="settings-section">
        <h3>证据卡筛选决定</h3>
        <Field
          label="本次决定理由"
          value={reason}
          set={setReason}
          placeholder="必须说明为何纳入、排除或保留待定"
          area
        />
        {project.evidence_cards.length ? (
          <ol className="results">
            {project.evidence_cards.map((card) => {
              const decision = byCard.get(card.id);
              return (
                <li key={card.id}>
                  <a href={card.canonical_url} target="_blank" rel="noreferrer">
                    {card.title}
                  </a>
                  <span>
                    {decision
                      ? `${decision.decision} · ${decision.reason}`
                      : "尚未按当前协议筛选"}
                  </span>
                  <div className="inline-actions">
                    <button
                      disabled={busy || !protocol?.active || !reason.trim()}
                      onClick={() => decide(card.id, "included")}
                    >
                      纳入
                    </button>
                    <button
                      className="danger"
                      disabled={busy || !protocol?.active || !reason.trim()}
                      onClick={() => decide(card.id, "excluded")}
                    >
                      排除
                    </button>
                    <button
                      className="quiet"
                      disabled={busy || !protocol?.active || !reason.trim()}
                      onClick={() => decide(card.id, "uncertain")}
                    >
                      待定
                    </button>
                  </div>
                </li>
              );
            })}
          </ol>
        ) : (
          <Empty text={'先在“文献与证据”保存数据源返回的证据卡。'} />
        )}
      </section>
      {state?.prisma && (
        <section className="settings-section">
          <h3>PRISMA 流程摘要</h3>
          <dl className="metric-grid">
            <div>
              <dt>识别</dt>
              <dd>{state.prisma.flow.records_identified}</dd>
            </div>
            <div>
              <dt>已筛选</dt>
              <dd>{state.prisma.flow.records_screened}</dd>
            </div>
            <div>
              <dt>纳入</dt>
              <dd>{state.prisma.flow.studies_included}</dd>
            </div>
            <div>
              <dt>排除</dt>
              <dd>{state.prisma.flow.records_excluded}</dd>
            </div>
            <div>
              <dt>待定</dt>
              <dd>{state.prisma.flow.records_uncertain}</dd>
            </div>
          </dl>
          {state.artifact && (
            <p className="file-path">
              {state.artifact.path} · SHA256 {state.artifact.sha256}
            </p>
          )}
        </section>
      )}
    </Panel>
  );
}

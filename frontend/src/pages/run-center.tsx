import React, { useState, useEffect, useMemo } from "react";
import {
  createHypothesis,
  download,
  reviseHypothesis,
  transitionHypothesis,
  type Project,
  type Workflow,
  type WorkflowRunCenter,
  type WorkflowInput,
  type HypothesisVersion,
  type HypothesisWrite,
} from "../api";
import { Panel, Empty, Field } from "../ui";
import { statusText, inputStatusText } from "../research-helpers";
import { workflowNames, workflowInputRequirements } from "../lib/workflow-meta";
import { fmtTime } from "../lib/format";

export function RunCenterPage({
  project,
  workflows,
  selectedId,
  snapshot,
  inputs,
  feedback,
  busy,
  onSelected,
  onFeedback,
  onRefresh,
  onCreate,
  onAction,
  onResolve,
  onUpload,
  onRemove,
  onSync,
  onDownload,
}: {
  project?: Project;
  workflows: Workflow[];
  selectedId: string;
  snapshot?: WorkflowRunCenter;
  inputs: WorkflowInput[];
  feedback: string;
  busy: boolean;
  onSelected: (id: string) => void;
  onFeedback: (value: string) => void;
  onRefresh: () => void;
  onCreate: () => void;
  onAction: (id: string, action: "start" | "pause" | "resume" | "restart") => void;
  onResolve: (action: "approve" | "feedback" | "stop") => void;
  onUpload: (files: File[]) => void;
  onRemove: (id: string) => void;
  onSync: (id: string) => void;
  onDownload: (workflow: Workflow) => void;
}) {
  if (!project)
    return (
      <Panel
        className="run-center-page"
        title="项目级运行中心"
        detail="研究项目是工作流、检查点、日志和产物的持久化边界。"
      >
        <Empty text="请先建立或选择研究合同。" />
      </Panel>
    );
  const selectedSnapshot =
    snapshot?.workflow.id === selectedId ? snapshot : undefined;
  const active = selectedSnapshot?.workflow;
  const inputRequirement = active
    ? workflowInputRequirements[active.template]
    : undefined;
  const checkpoint = selectedSnapshot?.checkpoint;
  const checkpointStep = checkpoint
    ? active?.steps?.find((step) => step.skill_name === checkpoint.step_name)
    : undefined;
  const checkpointNeedsFeedback = checkpoint?.checkpoint_type === "feedback";
  return (
    <Panel
      className="run-center-page"
      title="项目级运行中心"
      detail="每个工作流均绑定当前研究合同；步骤、检查点、日志和产物均从同一持久化快照读取。"
    >
      <div className="toolbar">
        <button className="quiet" disabled={busy} onClick={onRefresh}>
          刷新运行快照
        </button>
        <button disabled={busy} onClick={onCreate}>
          新建工作流
        </button>
      </div>
      {workflows.length ? (
        <div className="run-center-layout">
          <section className="workflow-list" aria-label="项目工作流">
            {workflows.map((workflow) => (
              <article
                className={selectedId === workflow.id ? "workflow selected" : "workflow"}
                key={workflow.id}
              >
                <button
                  type="button"
                  className="workflow-select"
                  aria-pressed={selectedId === workflow.id}
                  onClick={() => onSelected(workflow.id)}
                >
                  <h3>{workflow.title}</h3>
                  <p>
                    {workflowNames[workflow.template] || workflow.template} ·
                    当前：{workflow.current_step || "等待启动"}
                  </p>
                <span className={`badge ${workflow.status}`}>
                  {statusText(workflow.status)}
                </span>
                </button>
                <div className="inline-actions">
                  <button
                    disabled={busy || !["pending", "paused"].includes(workflow.status)}
                    onClick={(e) => { e.stopPropagation(); onAction(workflow.id, workflow.status === "paused" ? "resume" : "start"); }}
                  >
                    {workflow.status === "paused" ? "恢复" : "启动"}
                  </button>
                  <button className="quiet" disabled={busy || workflow.status !== "running"}
                    onClick={(e) => { e.stopPropagation(); onAction(workflow.id, "pause"); }}>
                    暂停
                  </button>
                  <button className="quiet" disabled={busy || workflow.status === "running"}
                    onClick={(e) => { e.stopPropagation(); onAction(workflow.id, "restart"); }}>
                    重启
                  </button>
                  <button className="quiet" disabled={busy}
                    onClick={(e) => { e.stopPropagation(); onDownload(workflow); }}>
                    导出
                  </button>
                  <button className="danger" disabled={busy}
                    onClick={(e) => { e.stopPropagation(); onRemove(workflow.id); }}>
                    删除
                  </button>
                </div>
              </article>
            ))}
          </section>
          {active ? (
            <section className="run-snapshot" aria-label="运行快照">
              <div className="section-command">
                <div>
                  <p className="eyebrow">{active.id}</p>
                  <h3>{active.title}</h3>
                </div>
                <span className={`badge ${active.status}`}>{statusText(active.status)}</span>
              </div>
              <section className="workflow-inputs">
                <div className="section-command">
                  <div>
                    <h4>输入资料</h4>
                    <p>原始文件保存在当前工作流的 user_data 目录，并记录大小、解析状态与 SHA256。</p>
                  </div>
                  <label className="button-like">
                    上传资料
                    <input type="file" multiple disabled={busy}
                      onChange={(e) => { onUpload(Array.from(e.currentTarget.files || [])); e.currentTarget.value = ""; }} />
                  </label>
                </div>
                {inputRequirement && !inputs.length && (
                  <div className="alert input-required" role="status">
                    {inputRequirement}上传后才能启动此工作流。
                  </div>
                )}
                {inputs.length ? (
                  <ol className="run-artifacts workflow-input-list">
                    {inputs.map((item) => (
                      <li key={item.path}>
                        <b>{item.path}</b>
                        <span>{item.size.toLocaleString()} bytes · {inputStatusText(item.status)}</span>
                        <small>SHA256 {item.sha256}</small>
                      </li>
                    ))}
                  </ol>
                ) : (
                  <Empty text="尚未上传输入资料；不依赖外部材料的工作流可以直接启动。" />
                )}
              </section>
              <section>
                <h4>执行 DAG</h4>
                <ol className="run-dag">
                  {(active.steps || []).map((step) => (
                    <li className={step.status} key={step.skill_name}>
                      <div>
                        <b>{step.step_order + 1}. {step.display_name}</b>
                        <span>{statusText(step.status)}</span>
                      </div>
                      {step.error_message && <small>{step.error_message}</small>}
                      {step.output_files.length ? <small>产出：{step.output_files.join("、")}</small> : null}
                    </li>
                  ))}
                </ol>
              </section>
              {checkpoint && (
                <section className="checkpoint-card" aria-labelledby="checkpoint-title">
                  <header className="checkpoint-header">
                    <div>
                      <p className="checkpoint-kicker">需要人工决策</p>
                      <h4 id="checkpoint-title">
                        {checkpointStep?.display_name || checkpoint.step_name}
                      </h4>
                      <p className="checkpoint-summary">
                        {checkpointNeedsFeedback
                          ? "请审阅当前产物，留下可执行的修改意见后再继续。"
                          : "请审阅当前产物；确认无误后可批准继续执行。"}
                      </p>
                    </div>
                    <span className="checkpoint-status">
                      {checkpointNeedsFeedback ? "待反馈" : "待批准"}
                    </span>
                  </header>
                  <p className="checkpoint-source">
                    检查点：<code>{checkpoint.step_name}</code>
                  </p>
                  <label className="checkpoint-feedback" htmlFor="checkpoint-feedback">
                    <span>审阅意见</span>
                    <span className="field-hint">可选；提交后将随本次检查点响应一并留档。</span>
                    <textarea
                      id="checkpoint-feedback"
                      value={feedback}
                      onChange={(e) => onFeedback(e.target.value)}
                      placeholder="例如：补充样本选择依据，并明确实验的对照条件。"
                    />
                  </label>
                  <footer className="checkpoint-actions">
                    <div className="inline-actions">
                      <button type="button" disabled={busy} onClick={() => onResolve("approve")}>
                        批准并继续
                      </button>
                      <button
                        type="button"
                        className="quiet"
                        disabled={busy || !feedback.trim()}
                        onClick={() => onResolve("feedback")}
                      >
                        提交修改意见
                      </button>
                      <button type="button" className="danger" disabled={busy} onClick={() => onResolve("stop")}>
                        终止工作流
                      </button>
                    </div>
                    <small>批准将继续执行；终止不会删除已生成的产物与审计记录。</small>
                  </footer>
                </section>
              )}
              <section>
                <div className="section-command">
                  <h4>产物血缘快照</h4>
                  {active.status === "completed" && (
                    <button className="quiet compact-action" disabled={busy}
                      title="将本工作流的文献检索结果同步至当前项目的证据库"
                      onClick={() => onSync(active.id)}>
                      ⇄ 同步至证据库
                    </button>
                  )}
                </div>
                {selectedSnapshot.artifacts.length ? (
                  <ol className="run-artifacts">
                    {selectedSnapshot.artifacts.map((item) => (
                      <li key={item.path}>
                        <b>{item.path}</b>
                        <span>{item.size.toLocaleString()} bytes · SHA256 {item.sha256}</span>
                        {item.producer_step && <small>生产步骤：{item.producer_step}</small>}
                      </li>
                    ))}
                  </ol>
                ) : (
                  <Empty text="当前工作区还没有可交付产物。" />
                )}
              </section>
              <section>
                <h4>实时日志</h4>
                {selectedSnapshot.logs.length ? (
                  <ol className="run-logs">
                    {selectedSnapshot.logs.map((entry, index) => (
                      <li key={`${entry.created_at}-${index}`}>
                        <time dateTime={entry.created_at}>{fmtTime(entry.created_at)}</time>
                        <b>{entry.step_name || "工作流"}</b>
                        <span className={entry.level}>{entry.message}</span>
                      </li>
                    ))}
                  </ol>
                ) : (
                  <Empty text="尚无持久化执行日志。" />
                )}
              </section>
            </section>
          ) : (
            <Empty text="选择一个工作流以查看其运行快照。" />
          )}
        </div>
      ) : (
        <Empty text="当前项目还没有工作流。创建工作流后，所有执行状态和产物将自动绑定到此项目。" />
      )}
    </Panel>
  );
}

export function ProjectCard({ project }: { project: Project }) {
  return (
    <div className="project-card">
      <div>
        <p className="eyebrow">当前研究合同</p>
        <h3>{project.title}</h3>
        <p>{project.research_question}</p>
      </div>
      <dl>
        <div><dt>状态</dt><dd>{statusText(project.status)}</dd></div>
        <div><dt>证据实体</dt><dd>{project.artifacts.length}</dd></div>
        <div><dt>审计事件</dt><dd>{project.events.length}</dd></div>
        <div><dt>冻结假设</dt><dd>{project.hypothesis_readiness?.frozen_count || 0}</dd></div>
      </dl>
    </div>
  );
}

const emptyHypothesis = (): HypothesisWrite => ({
  statement: "",
  mechanism: "",
  prediction: "",
  falsification_criteria: "",
  boundary_conditions: "",
});

export function HypothesisWorkbench({
  project,
  busy,
  onRun,
  onChanged,
}: {
  project: Project;
  busy: boolean;
  onRun: (action: () => Promise<void>) => Promise<void>;
  onChanged: (project: Project) => Promise<void>;
}) {
  const [form, setForm] = useState<HypothesisWrite>(emptyHypothesis),
    [editingVersionId, setEditingVersionId] = useState(""),
    [changeReason, setChangeReason] = useState(""),
    [transitionReason, setTransitionReason] = useState(
      "研究者已核对机制、可观察预测、证伪标准与边界条件。",
    );
  const hypotheses = project.hypotheses || [];
  const current = hypotheses.filter((item) => item.is_current);
  const historical = hypotheses.filter((item) => !item.is_current);
  const readiness = project.hypothesis_readiness || {
    ready: false,
    current_count: current.length,
    frozen_count: current.filter((item) => item.status === "frozen").length,
    falsified_count: current.filter((item) => item.status === "falsified").length,
    rule: "验证性实验前至少冻结一条当前假设。",
  };
  useEffect(() => {
    setForm(emptyHypothesis());
    setEditingVersionId("");
    setChangeReason("");
  }, [project.id]);
  useEffect(() => {
    if (editingVersionId && !current.some((item) => item.id === editingVersionId && item.status === "draft")) {
      setEditingVersionId("");
      setForm(emptyHypothesis());
    }
  }, [editingVersionId, project.hypotheses]);
  const update = (key: keyof HypothesisWrite, value: string) =>
    setForm((prev) => ({ ...prev, [key]: value }));
  const complete = Object.values(form).every((value) => value.trim());
  const submit = () =>
    onRun(async () => {
      if (!complete || !changeReason.trim())
        throw new Error("五项假设字段和变更理由均为必填项");
      const updated = editingVersionId
        ? await reviseHypothesis(project.id, editingVersionId, form, changeReason.trim())
        : await createHypothesis(project.id, form, changeReason.trim());
      await onChanged(updated);
      setEditingVersionId("");
      setForm(emptyHypothesis());
      setChangeReason("");
    });
  const edit = (item: HypothesisVersion) => {
    setEditingVersionId(item.id);
    setForm({
      statement: item.statement,
      mechanism: item.mechanism,
      prediction: item.prediction,
      falsification_criteria: item.falsification_criteria,
      boundary_conditions: item.boundary_conditions,
    });
    setChangeReason("");
  };
  const transition = (item: HypothesisVersion, action: "freeze" | "unfreeze" | "falsify") =>
    onRun(async () => {
      if (!transitionReason.trim()) throw new Error("状态变更必须填写理由");
      const updated = await transitionHypothesis(project.id, item.id, action, transitionReason.trim());
      await onChanged(updated);
    });
  const renderVersion = (item: HypothesisVersion) => (
    <article className={`hypothesis-card hypothesis-${item.status}`} key={item.id}>
      <header>
        <div>
          <span>H-{item.hypothesis_id.slice(0, 8)} · v{item.version}</span>
          <h4>{item.statement}</h4>
        </div>
        <strong>{statusText(item.status)}</strong>
      </header>
      <dl className="hypothesis-fields">
        <div><dt>机制</dt><dd>{item.mechanism}</dd></div>
        <div><dt>可观察预测</dt><dd>{item.prediction}</dd></div>
        <div><dt>证伪标准</dt><dd>{item.falsification_criteria}</dd></div>
        <div><dt>边界条件</dt><dd>{item.boundary_conditions}</dd></div>
      </dl>
      <div className="hypothesis-provenance">
        <span>创建者 {item.created_by}</span>
        <span>变更理由：{item.change_reason}</span>
        {item.state_reason && <span>状态理由：{item.state_reason}</span>}
      </div>
      {item.manifest ? (
        <div className="hypothesis-manifest">
          <b>不可变假设清单</b>
          <code>{item.manifest.path}</code>
          <span>SHA256 {item.manifest.sha256}</span>
          <button className="quiet" disabled={busy}
            onClick={() => onRun(() => download(
              `/api/editor/${project.id}/download?path=${encodeURIComponent(item.manifest!.path)}`,
              `hypothesis-${item.hypothesis_id}-v${item.version}.json`,
            ))}>
            下载并独立核验
          </button>
        </div>
      ) : item.status === "frozen" ? (
        <div className="review-failure">冻结状态缺少可核验清单，实验门禁将阻断。</div>
      ) : null}
      {item.events?.length ? (
        <details>
          <summary>{item.events.length} 条生命周期事件</summary>
          <ol className="hypothesis-events">
            {item.events.map((event) => (
              <li key={event.id}>
                <b>{event.event_type}</b>
                <span>{event.actor} · {event.reason}</span>
                <time dateTime={event.created_at}>{fmtTime(event.created_at)}</time>
              </li>
            ))}
          </ol>
        </details>
      ) : null}
      {item.is_current && project.status !== "approved" && (
        <div className="inline-actions">
          {item.status === "draft" && (
            <>
              <button className="quiet" disabled={busy} onClick={() => edit(item)}>创建修订</button>
              <button disabled={busy || !transitionReason.trim()} onClick={() => transition(item, "freeze")}>冻结并锁定清单</button>
            </>
          )}
          {item.status === "frozen" && (
            <button className="quiet" disabled={busy || !transitionReason.trim()} onClick={() => transition(item, "unfreeze")}>解冻并使下游失效</button>
          )}
          {(item.status === "draft" || item.status === "frozen") && (
            <button className="danger" disabled={busy || !transitionReason.trim()} onClick={() => transition(item, "falsify")}>记录证伪</button>
          )}
        </div>
      )}
    </article>
  );
  return (
    <section className="hypothesis-workbench" aria-label="可证伪假设注册表">
      <div className="section-command">
        <div>
          <p className="eyebrow">Hypothesis lifecycle</p>
          <h3>可证伪假设注册表</h3>
          <p>登记或修订会生成不可变清单，冻结后验证性实验、稿件和独立审查才能绑定该 SHA256。</p>
        </div>
        <span className={`readiness-badge ${readiness.ready ? "ready" : "blocked"}`}>
          {readiness.ready ? "验证性工作就绪" : "验证性工作已阻断"}
        </span>
      </div>
      <div className="hypothesis-readiness">
        <span>当前 {readiness.current_count}</span>
        <span>已冻结 {readiness.frozen_count}</span>
        <span>已证伪 {readiness.falsified_count}</span>
        <small>{readiness.rule}</small>
      </div>
      <label className="wide transition-reason">
        状态变更理由
        <textarea value={transitionReason} onChange={(e) => setTransitionReason(e.target.value)} />
      </label>
      {current.length
        ? <div className="hypothesis-list">{current.map(renderVersion)}</div>
        : <Empty text="先登记一条包含机制、预测、证伪标准和边界条件的假设。" />}
      <section className="hypothesis-editor">
        <div className="section-command">
          <div>
            <p className="eyebrow">{editingVersionId ? "Version revision" : "New hypothesis"}</p>
            <h3>{editingVersionId ? "创建新版本" : "登记研究假设"}</h3>
          </div>
          {editingVersionId && (
            <button className="quiet" onClick={() => { setEditingVersionId(""); setForm(emptyHypothesis()); setChangeReason(""); }}>
              取消修订
            </button>
          )}
        </div>
        <div className="form-grid hypothesis-form">
          <Field label="假设陈述" value={form.statement} set={(v) => update("statement", v)} area placeholder="明确变量、方向和可被反驳的关系" />
          <Field label="机制" value={form.mechanism} set={(v) => update("mechanism", v)} area placeholder="说明为何可能发生，而非只重复相关关系" />
          <Field label="可观察预测" value={form.prediction} set={(v) => update("prediction", v)} area placeholder="给出可由数据或实验观察的结果" />
          <Field label="证伪标准" value={form.falsification_criteria} set={(v) => update("falsification_criteria", v)} area placeholder="哪些结果出现时必须拒绝或修订假设" />
          <Field label="边界条件" value={form.boundary_conditions} set={(v) => update("boundary_conditions", v)} area placeholder="限定人群、场景、时间和适用范围" />
          <Field label="登记 / 修订理由" value={changeReason} set={setChangeReason} area placeholder="说明本版本为何产生；该理由写入审计事件" />
        </div>
        <button disabled={busy || !complete || !changeReason.trim()} onClick={submit}>
          {editingVersionId ? "保存为下一版本" : "登记草拟假设"}
        </button>
      </section>
      {historical.length ? (
        <details className="hypothesis-history">
          <summary>历史版本（{historical.length}）</summary>
          <div className="hypothesis-list">{historical.map(renderVersion)}</div>
        </details>
      ) : null}
    </section>
  );
}

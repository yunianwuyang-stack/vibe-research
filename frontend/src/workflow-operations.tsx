import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import {
  getWorkflowOperationsDetail,
  listWorkflowOperations,
  recoverWorkflow,
  retryWorkflowStep,
  streamWorkflowOperationsEvents,
  type Project,
  type WorkflowOperationsDetail,
  type WorkflowOperationsEvent,
  type WorkflowOperationsRun,
  type WorkflowOperationsSnapshot,
} from "./api";

type StreamState = "connecting" | "live" | "retrying" | "offline";
type DetailTab = "dag" | "logs" | "artifacts" | "recovery";

const STATUS_OPTIONS = [
  ["", "全部状态"],
  ["running", "运行中"],
  ["failed", "失败"],
  ["paused", "已暂停"],
  ["pending", "待启动"],
  ["completed", "已完成"],
] as const;

const statusText = (status?: string | null) =>
  ({
    pending: "待启动",
    queued: "排队中",
    running: "运行中",
    paused: "已暂停",
    failed: "失败",
    completed: "已完成",
    waiting_checkpoint: "等待确认",
    interrupted: "已中断",
    accepted: "已受理",
  })[status || ""] || status || "未知";

const eventText = (event: WorkflowOperationsEvent) => {
  const nested = event.data.payload;
  const data = nested && typeof nested === "object" && !Array.isArray(nested)
    ? { ...event.data, ...(nested as Record<string, unknown>) }
    : event.data;
  const message = data.message || data.error || data.detail;
  if (typeof message === "string" && message.trim()) return message;
  const step = data.skill_name || data.step || data.step_name;
  if (typeof step === "string" && step) return `${statusText(String(data.status || event.event))} · ${step}`;
  return statusText(event.event.replace(/^workflow_|^step_/, ""));
};

const formatTime = (value?: string | null) => {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString("zh-CN", { hour12: false });
};

const shortHash = (value?: string | null) =>
  value ? `${value.slice(0, 10)}…${value.slice(-8)}` : "—";

const recoveryTargetText = (target?: { skill_name: string; display_name?: string | null } | null) =>
  target?.display_name || target?.skill_name || "失败节点";

const emptySnapshot = (): WorkflowOperationsSnapshot => ({
  summary: {
    total: 0,
    pending: 0,
    running: 0,
    paused: 0,
    failed: 0,
    completed: 0,
    recoverable: 0,
  },
  runs: [],
  pagination: { limit: 200, offset: 0, total: 0 },
});

export function WorkflowOperationsPage({
  projects,
  activeProjectId,
  onCreate,
  onOpenRun,
  onOpenEditor,
}: {
  projects: Project[];
  activeProjectId?: string;
  onCreate: () => void;
  onOpenRun: (projectId: string | null | undefined, workflowId: string) => void;
  onOpenEditor: (projectId: string | null | undefined, workflowId: string) => void;
}) {
  const [projectFilter, setProjectFilter] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [query, setQuery] = useState("");
  const [snapshot, setSnapshot] = useState<WorkflowOperationsSnapshot>(emptySnapshot);
  const [selectedId, setSelectedId] = useState("");
  const [detail, setDetail] = useState<WorkflowOperationsDetail>();
  const [detailTab, setDetailTab] = useState<DetailTab>("dag");
  const [loading, setLoading] = useState(true);
  const [detailLoading, setDetailLoading] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [actionBusy, setActionBusy] = useState("");
  const [recoveryReason, setRecoveryReason] = useState(
    "研究者确认从最近失败节点恢复，并保留既有成功产物与审计记录。",
  );
  const [streamState, setStreamState] = useState<StreamState>("connecting");
  const [liveEvents, setLiveEvents] = useState<WorkflowOperationsEvent[]>([]);
  const [refreshNonce, setRefreshNonce] = useState(0);
  const lastEventId = useRef(0);
  const refreshTimer = useRef<number | undefined>(undefined);

  const projectNames = useMemo(
    () => new Map(projects.map((project) => [project.id, project.title])),
    [projects],
  );

  const refreshList = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const value = await listWorkflowOperations({
        project_id: projectFilter || undefined,
        status: statusFilter || undefined,
        limit: 200,
      });
      setSnapshot(value);
      setSelectedId((current) =>
        value.runs.some((run) => run.id === current) ? current : value.runs[0]?.id || "",
      );
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "无法读取全局运行快照");
    } finally {
      setLoading(false);
    }
  }, [projectFilter, statusFilter]);

  const refreshDetail = useCallback(async (workflowId: string) => {
    setDetailLoading(true);
    try {
      const value = await getWorkflowOperationsDetail(workflowId);
      setDetail(value);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "无法读取工作流执行证据");
    } finally {
      setDetailLoading(false);
    }
  }, []);

  useEffect(() => {
    void refreshList();
  }, [refreshList, refreshNonce]);

  useEffect(() => {
    if (!selectedId) {
      setDetail(undefined);
      return;
    }
    setDetail(undefined);
    void refreshDetail(selectedId);
  }, [selectedId, refreshDetail]);

  useEffect(() => {
    const controller = new AbortController();
    let stopped = false;
    const wait = (milliseconds: number) =>
      new Promise<void>((resolve) => window.setTimeout(resolve, milliseconds));
    const scheduleRefresh = () => {
      window.clearTimeout(refreshTimer.current);
      refreshTimer.current = window.setTimeout(() => {
        setRefreshNonce((value) => value + 1);
        if (selectedId) void refreshDetail(selectedId);
      }, 220);
    };
    const connect = async () => {
      let retryDelay = 700;
      while (!stopped && !controller.signal.aborted) {
        setStreamState(lastEventId.current ? "retrying" : "connecting");
        try {
          await streamWorkflowOperationsEvents(
            {
              after_id: lastEventId.current || undefined,
              project_id: projectFilter || undefined,
            },
            (event) => {
              if (event.id) lastEventId.current = Math.max(lastEventId.current, event.id);
              setStreamState("live");
              if (event.event !== "heartbeat") {
                setLiveEvents((items) => [event, ...items].slice(0, 80));
                scheduleRefresh();
              }
            },
            controller.signal,
          );
          retryDelay = 700;
        } catch (caught) {
          if (controller.signal.aborted) break;
          setStreamState("retrying");
          await wait(retryDelay);
          retryDelay = Math.min(retryDelay * 2, 5000);
        }
      }
      if (!controller.signal.aborted) setStreamState("offline");
    };
    void connect();
    return () => {
      stopped = true;
      controller.abort();
      window.clearTimeout(refreshTimer.current);
    };
  }, [projectFilter, selectedId, refreshDetail]);

  const visibleRuns = useMemo(() => {
    const normalized = query.trim().toLocaleLowerCase("zh-CN");
    if (!normalized) return snapshot.runs;
    return snapshot.runs.filter((run) =>
      [run.title, run.template, run.project_title, run.current_step, run.id]
        .filter(Boolean)
        .some((value) => String(value).toLocaleLowerCase("zh-CN").includes(normalized)),
    );
  }, [query, snapshot.runs]);

  const selectedRun = snapshot.runs.find((run) => run.id === selectedId);
  const selectedEvents = liveEvents.filter((event) => {
    const workflowId = event.data.workflow_id || event.data.workflowId;
    return !workflowId || String(workflowId) === selectedId;
  });

  const runAction = async (key: string, action: () => Promise<unknown>) => {
    if (!recoveryReason.trim()) {
      setError("请先填写恢复原因；该说明会进入持久化审计记录。");
      return;
    }
    setActionBusy(key);
    setError("");
    setNotice("");
    try {
      await action();
      setNotice("恢复操作已受理。执行器将在同一工作区保留成功节点，并从目标节点继续运行。");
      await Promise.all([refreshList(), selectedId ? refreshDetail(selectedId) : Promise.resolve()]);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "恢复操作未完成");
    } finally {
      setActionBusy("");
    }
  };

  const summaryCards: Array<[string, number, string]> = [
    ["全部运行", snapshot.summary.total, "total"],
    ["正在执行", snapshot.summary.running, "running"],
    ["可恢复", snapshot.summary.recoverable, "recoverable"],
    ["失败", snapshot.summary.failed, "failed"],
    ["已暂停", snapshot.summary.paused, "paused"],
    ["已完成", snapshot.summary.completed, "completed"],
  ];

  return (
    <section className="operations-page" aria-label="跨项目工作流运营台">
      <header className="operations-heading">
        <div>
          <p className="eyebrow">RESEARCH OPERATIONS / LIVE</p>
          <h1>全局工作流运营台</h1>
          <p>
            跨项目观察执行 DAG、持久日志、节点尝试与产物血缘；恢复动作由真实执行器受理，而不是只改变界面状态。
          </p>
        </div>
        <div className={`operations-stream ${streamState}`} role="status" aria-live="polite">
          <i aria-hidden="true" />
          <span>{streamState === "live" ? "事件流已连接" : streamState === "retrying" ? "事件流重连中" : streamState === "offline" ? "事件流已断开" : "连接事件流"}</span>
          <small>{lastEventId.current ? `事件 #${lastEventId.current}` : "等待首个心跳"}</small>
        </div>
      </header>

      <div className="operations-metrics" aria-label="运行汇总">
        {summaryCards.map(([label, value, tone]) => (
          <article className={tone} key={label}>
            <span>{label}</span>
            <strong>{value}</strong>
            <small>{label === "可恢复" ? "具有失败/中断恢复目标" : "持久化工作流"}</small>
          </article>
        ))}
      </div>

      <div className="operations-toolbar">
        <label>
          <span>项目范围</span>
          <select value={projectFilter} onChange={(event) => setProjectFilter(event.target.value)}>
            <option value="">全部研究项目</option>
            {projects.map((project) => <option value={project.id} key={project.id}>{project.title}</option>)}
          </select>
        </label>
        <label>
          <span>执行状态</span>
          <select value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)}>
            {STATUS_OPTIONS.map(([value, label]) => <option value={value} key={value || "all"}>{label}</option>)}
          </select>
        </label>
        <label className="operations-search">
          <span>定位运行</span>
          <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="项目、模板、当前节点或运行 ID" />
        </label>
        <button type="button" className="quiet" disabled={loading} onClick={() => void refreshList()}>刷新快照</button>
        <button type="button" onClick={onCreate}>新建工作流</button>
      </div>

      {error ? <div className="operations-alert error" role="alert">{error}</div> : null}
      {notice ? <div className="operations-alert success" role="status">{notice}</div> : null}

      <div className="operations-grid">
        <aside className="operations-runs" aria-label="跨项目运行队列">
          <header>
            <div>
              <span>RUN QUEUE</span>
              <b>{visibleRuns.length} / {snapshot.pagination.total}</b>
            </div>
            {loading ? <small>读取中…</small> : <small>按更新时间聚合</small>}
          </header>
          <div className="operations-run-list">
            {visibleRuns.map((run) => (
              <RunCard
                key={run.id}
                run={run}
                projectName={run.project_title || projectNames.get(run.project_id || "") || "未绑定项目"}
                selected={run.id === selectedId}
                onSelect={() => setSelectedId(run.id)}
              />
            ))}
            {!loading && !visibleRuns.length ? (
              <div className="operations-empty">当前筛选条件下没有工作流运行。</div>
            ) : null}
          </div>
        </aside>

        <main className="operations-inspector">
          {selectedRun ? (
            <>
              <header className="operations-run-heading">
                <div>
                  <div className="operations-breadcrumb">
                    <span>{selectedRun.project_title || projectNames.get(selectedRun.project_id || "") || "未绑定项目"}</span>
                    <i>/</i>
                    <code>{selectedRun.id}</code>
                  </div>
                  <h2>{selectedRun.title}</h2>
                  <p>{selectedRun.template} · 当前节点 {selectedRun.current_step || "等待调度"}</p>
                  <StatePlanes state={detail?.workflow.state || selectedRun.state} />
                </div>
                <div className="operations-heading-actions">
                  <span className={`ops-status ${selectedRun.status}`}>{statusText(selectedRun.status)}</span>
                  <button type="button" className="quiet" onClick={() => onOpenRun(selectedRun.project_id, selectedRun.id)}>项目运行中心</button>
                  <button type="button" className="quiet" onClick={() => onOpenEditor(selectedRun.project_id, selectedRun.id)}>打开产物编辑器</button>
                </div>
              </header>

              <section className="operations-recovery-command" aria-label="失败恢复控制">
                <div>
                  <span>RECOVERY COMMAND</span>
                  <b>{selectedRun.recoverable ? `可从 ${recoveryTargetText(detail?.recovery_target || selectedRun.recovery_target)} 恢复` : "当前没有待恢复节点"}</b>
                  <small>每次恢复都会新建 attempt 和 recovery operation，旧日志与产物哈希保持不变。</small>
                </div>
                <label>
                  <span>恢复原因（写入审计）</span>
                  <input value={recoveryReason} onChange={(event) => setRecoveryReason(event.target.value)} />
                </label>
                <button type="button"
                  disabled={!selectedRun.recoverable || Boolean(actionBusy)}
                  onClick={() => void runAction("recover", () => recoverWorkflow(selectedRun.id, recoveryReason))}
                >
                  {actionBusy === "recover" ? "正在受理…" : "从失败点恢复"}
                </button>
              </section>

              <div className="operations-tabs" role="group" aria-label="运行证据视图">
                {([
                  ["dag", "执行 DAG"],
                  ["logs", `持久日志 ${detail?.logs.length ?? 0}`],
                  ["artifacts", `产物血缘 ${detail?.artifacts.length ?? selectedRun.artifact_count}`],
                  ["recovery", `尝试与恢复 ${(detail?.attempts.length || 0) + (detail?.recoveries.length || 0)}`],
                ] as Array<[DetailTab, string]>).map(([key, label]) => (
                  <button
                    type="button"
                    className={detailTab === key ? "active" : ""}
                    aria-pressed={detailTab === key}
                    key={key}
                    onClick={() => setDetailTab(key)}
                  >
                    {label}
                  </button>
                ))}
              </div>

              {detailLoading && !detail ? <div className="operations-loading">正在读取执行证据…</div> : null}
              {detail ? (
                <div className="operations-tab-body">
                  {detailTab === "dag" ? (
                    <DagView
                      detail={detail}
                      busy={actionBusy}
                      onRetry={(skillName) => void runAction(`retry:${skillName}`, () => retryWorkflowStep(selectedRun.id, skillName, recoveryReason))}
                    />
                  ) : null}
                  {detailTab === "logs" ? <LogView logs={detail.logs} events={selectedEvents} /> : null}
                  {detailTab === "artifacts" ? <ArtifactView detail={detail} /> : null}
                  {detailTab === "recovery" ? <RecoveryView detail={detail} /> : null}
                </div>
              ) : null}
            </>
          ) : (
            <div className="operations-empty inspector-empty">
              <b>选择一条运行</b>
              <span>这里会显示真实 DAG、日志、恢复记录与可校验产物。</span>
            </div>
          )}
        </main>
      </div>

      {activeProjectId ? <p className="operations-footnote">当前编辑上下文：{projectNames.get(activeProjectId) || activeProjectId}；运营台筛选不会悄悄切换项目。</p> : null}
    </section>
  );
}


function StatePlanes({ state }: { state?: { transport: string; execution: string; assurance: string; root_cause: string; remediation: string } }) {
  if (!state) return null;
  const labels = [["transport", "传输"], ["execution", "执行"], ["assurance", "保证"]] as const;
  return <div className="operations-state-planes" aria-label="传输执行保证状态"><div className="state-plane-badges">{labels.map(([key, label]) => <span className={`state-plane ${state[key]}`} key={key}><b>{label}</b>{state[key]}</span>)}</div><small>根因：{state.root_cause} · 修复动作：{state.remediation}</small></div>;
}

function RunCard({
  run,
  projectName,
  selected,
  onSelect,
}: {
  run: WorkflowOperationsRun;
  projectName: string;
  selected: boolean;
  onSelect: () => void;
}) {
  return (
    <button
      type="button"
      className={`operations-run ${selected ? "selected" : ""}`}
      aria-pressed={selected}
      onClick={onSelect}
    >
      <span className="operations-run-project">{projectName}</span>
      <span className="operations-run-title">
        <b>{run.title}</b>
        <em className={`ops-status ${run.status}`}>{statusText(run.status)}</em>
      </span>
      <span className="operations-run-step">{run.current_step || "等待启动"}</span>
      <span className="operations-progress" aria-label={`完成度 ${run.progress.percent}%`}>
        <i style={{ width: `${Math.max(0, Math.min(100, run.progress.percent || 0))}%` }} />
      </span>
      <span className="operations-run-meta">
        <small>{run.progress.completed}/{run.progress.total} 节点</small>
        <small>{run.artifact_count} 个产物</small>
        <small>{formatTime(run.updated_at)}</small>
      </span>
      {run.latest_log?.message ? <span className="operations-last-log">{run.latest_log.message}</span> : null}
    </button>
  );
}

function DagView({
  detail,
  busy,
  onRetry,
}: {
  detail: WorkflowOperationsDetail;
  busy: string;
  onRetry: (skillName: string) => void;
}) {
  const steps = detail.workflow.steps || [];
  return (
    <section className="operations-dag" aria-label="持久化执行 DAG">
      {steps.map((step, index) => (
        <article className={`operations-node ${step.status}`} key={step.skill_name}>
          <div className="operations-node-index"><span>{String(index + 1).padStart(2, "0")}</span><i /></div>
          <div className="operations-node-card">
            <header>
              <div>
                <code>{step.skill_name}</code>
                <h3>{step.display_name}</h3>
              </div>
              <span className={`ops-status ${step.status}`}>{statusText(step.status)}</span>
            </header>
            <dl>
              <div><dt>开始</dt><dd>{formatTime(step.started_at)}</dd></div>
              <div><dt>完成</dt><dd>{formatTime(step.completed_at)}</dd></div>
              <div><dt>声明产物</dt><dd>{step.output_files.length}</dd></div>
            </dl>
            {step.output_files.length ? <p className="operations-node-outputs">{step.output_files.join(" · ")}</p> : null}
            {step.error_message ? <p className="operations-node-error">{step.error_message}</p> : null}
            {step.status === "failed" || step.status === "interrupted" ? (
              <button type="button" disabled={Boolean(busy)} onClick={() => onRetry(step.skill_name)}>
                {busy === `retry:${step.skill_name}` ? "正在创建重试…" : "仅重试此失败节点"}
              </button>
            ) : null}
          </div>
        </article>
      ))}
      {!steps.length ? <div className="operations-empty">该运行尚未持久化 DAG 节点。</div> : null}
    </section>
  );
}

function LogView({ logs, events }: { logs: WorkflowOperationsDetail["logs"]; events: WorkflowOperationsEvent[] }) {
  return (
    <section className="operations-log-view">
      {events.length ? (
        <div className="operations-live-strip">
          <span>LIVE</span>
          <b>{eventText(events[0])}</b>
          <small>事件 #{events[0].id || "heartbeat"}</small>
        </div>
      ) : null}
      <ol className="operations-log-list">
        {[...logs].reverse().map((entry, index) => (
          <li key={`${entry.id || index}-${entry.created_at}`}>
            <time>{formatTime(entry.created_at)}</time>
            <b>{entry.step_name || "workflow"}</b>
            <span className={entry.level}>{entry.message}</span>
          </li>
        ))}
      </ol>
      {!logs.length ? <div className="operations-empty">尚无持久化执行日志。</div> : null}
    </section>
  );
}

function ArtifactView({ detail }: { detail: WorkflowOperationsDetail }) {
  return (
    <section className="operations-artifacts">
      <header><span>PATH</span><span>PRODUCER / ATTEMPT</span><span>SIZE</span><span>SHA256 / PREDECESSOR</span></header>
      {detail.artifacts.map((artifact) => (
        <article className={artifact.exists === false ? "missing" : ""} key={`${artifact.path}-${artifact.sha256}`}>
          <div><b>{artifact.path}</b><small>{artifact.exists === false ? "当前文件缺失；血缘记录保留" : "文件存在且已校验"}</small></div>
          <div><b>{artifact.producer_step || "workspace"}</b><small>attempt {artifact.attempt_id ?? "—"}</small></div>
          <div><b>{artifact.size.toLocaleString()} B</b><small>{formatTime(artifact.recorded_at)}</small></div>
          <div><code title={artifact.sha256}>{shortHash(artifact.sha256)}</code><small title={artifact.predecessor_sha256 || ""}>前序 {shortHash(artifact.predecessor_sha256)}</small></div>
        </article>
      ))}
      {!detail.artifacts.length ? <div className="operations-empty">当前工作区没有可交付产物。</div> : null}
    </section>
  );
}

function RecoveryView({ detail }: { detail: WorkflowOperationsDetail }) {
  const records = [
    ...detail.recoveries.map((record) => ({ kind: "恢复操作", record })),
    ...detail.attempts.map((record) => ({ kind: "节点尝试", record })),
  ];
  return (
    <section className="operations-recovery-ledger">
      <div className="operations-ledger-summary">
        <div><span>节点尝试</span><b>{detail.attempts.length}</b></div>
        <div><span>恢复操作</span><b>{detail.recoveries.length}</b></div>
        <div><span>持久事件</span><b>{detail.events.length}</b></div>
      </div>
      <ol>
        {records.map(({ kind, record }, index) => (
          <li key={`${kind}-${String(record.id || record.operation_id || index)}`}>
            <span>{kind}</span>
            <div>
              <b>{String(record.skill_name || record.operation_id || record.id || "workflow")}</b>
              <small>{String(record.reason || record.error_message || "执行器状态变更")}</small>
            </div>
            <em className={`ops-status ${String(record.status || "pending")}`}>{statusText(String(record.status || "pending"))}</em>
            <time>{formatTime(String(record.finished_at || record.completed_at || record.created_at || record.started_at || ""))}</time>
            <details><summary>原始审计字段</summary><pre>{JSON.stringify(record, null, 2)}</pre></details>
          </li>
        ))}
      </ol>
      {!records.length ? <div className="operations-empty">尚无恢复或重试记录；普通成功执行不会伪造恢复审计。</div> : null}
    </section>
  );
}

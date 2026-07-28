import React, { useState, useEffect } from "react";
import {
  api,
  type ModelProfile,
  type ModelProfileTest,
  type ModelProfileUpdate,
  type AgentTask,
  type AgentCollaboration,
  type Project,
} from "../api";
import { Panel, Empty, Field } from "../ui";
import { statusText } from "../research-helpers";
import {
  applyTheme,
  safeThemeColor,
  type ThemePreset,
  type ThemeColors,
} from "../lib/theme";

// ─── JSON viewer ────────────────────────────────────────────────────────────

function JsonCard({ value }: { value: unknown }) {
  return (
    <pre className="json-card">{JSON.stringify(value, null, 2)}</pre>
  );
}

// ─── Model profile editor ────────────────────────────────────────────────────

const MODEL_ROLE_LABELS: Record<ModelProfile["role"], string> = {
  executor: "执行器",
  reviewer: "独立审稿人",
  editor_ai: "科研编辑",
};

function LocalizedModelProfileEditor({
  profile,
  test,
  busy,
  onSave,
  onTest,
}: {
  profile: ModelProfile;
  test?: ModelProfileTest;
  busy: boolean;
  onSave: (role: ModelProfile["role"], value: ModelProfileUpdate) => Promise<void>;
  onTest: (role: ModelProfile["role"]) => Promise<void>;
}) {
  const [draft, setDraft] = useState<ModelProfileUpdate>(() => profile),
    [apiKey, setApiKey] = useState(""),
    [clearKey, setClearKey] = useState(false);
  useEffect(() => {
    setDraft(profile);
    setApiKey("");
    setClearKey(false);
  }, [profile]);
  const update = <K extends keyof ModelProfileUpdate>(key: K, value: ModelProfileUpdate[K]) =>
    setDraft((current) => ({ ...current, [key]: value }));
  const save = async () => {
    await onSave(profile.role, { ...draft, api_key: apiKey || undefined, clear_api_key: clearKey });
    setApiKey("");
  };
  return (
    <article className="model-profile">
      <header>
        <div>
          <p className="eyebrow">{MODEL_ROLE_LABELS[profile.role]}</p>
          <h4>{profile.name}</h4>
        </div>
        <span className={profile.api_key_configured ? "profile-key configured" : "profile-key"}>
          {profile.api_key_configured ? "密钥已配置" : "未配置密钥"}
        </span>
      </header>
      <div className="profile-fields">
        <label>
          服务商与协议
          <select
            aria-label={`${MODEL_ROLE_LABELS[profile.role]}服务商与协议`}
            value={draft.provider}
            onChange={(e) => update("provider", e.target.value as ModelProfile["provider"])}
          >
            <option value="openai_compatible">OpenAI 聊天补全</option>
            <option value="openai_responses">OpenAI 响应协议</option>
            <option value="anthropic_messages">Anthropic 消息协议</option>
            <option value="gemini_generate_content">Gemini 内容生成</option>
          </select>
        </label>
        <Field label="服务地址（Base URL）" value={draft.base_url}
          set={(v) => update("base_url", v)} placeholder="https://share-api.com/v1 或任意 OpenAI 兼容地址" />
        <Field label="模型 ID" value={draft.model_id} set={(v) => update("model_id", v)} placeholder="模型 ID" />
        <label>
          温度
          <input type="number" min="0" max="2" step="0.05" value={draft.temperature}
            onChange={(e) => update("temperature", Number(e.target.value))} />
        </label>
        <label>
          Top P
          <input type="number" min="0" max="1" step="0.05" value={draft.top_p}
            onChange={(e) => update("top_p", Number(e.target.value))} />
        </label>
        <label>
          最大输出 Token
          <input type="number" min="1" max="32768" step="1" value={draft.max_tokens}
            onChange={(e) => update("max_tokens", Number(e.target.value))} />
        </label>
        <label>
          推理强度
          <select value={draft.reasoning_effort}
            onChange={(e) => update("reasoning_effort", e.target.value as ModelProfile["reasoning_effort"])}>
            <option value="">不启用</option>
            <option value="minimal">最低</option>
            <option value="low">低</option>
            <option value="medium">中</option>
            <option value="high">高</option>
          </select>
        </label>
        <label className="wide">
          API 密钥
          <input type="password" autoComplete="new-password" value={apiKey}
            placeholder={profile.api_key_configured ? "已配置；留空保留" : "未配置"}
            onChange={(e) => setApiKey(e.target.value)} />
        </label>
        {profile.api_key_configured && (
          <label className="check-field wide">
            <input type="checkbox" checked={clearKey} onChange={(e) => setClearKey(e.target.checked)} />
            清除已保存密钥
          </label>
        )}
      </div>
      <div className="actions">
        <button disabled={busy || !draft.base_url.trim() || !draft.model_id.trim()} onClick={save}>
          保存档案
        </button>
        <button className="quiet" disabled={busy} onClick={() => onTest(profile.role)}>
          测试连接
        </button>
      </div>
      {test && (
        <p className={`profile-test ${test.ok ? "success" : "failure"}`} role="status">
          {test.ok ? "连接成功" : "连接失败"} · {test.message}
        </p>
      )}
    </article>
  );
}

function ModelProfiles({
  profiles, tests, busy, onSave, onTest,
}: {
  profiles: ModelProfile[];
  tests: Record<string, ModelProfileTest>;
  busy: boolean;
  onSave: (role: ModelProfile["role"], value: ModelProfileUpdate) => Promise<void>;
  onTest: (role: ModelProfile["role"]) => Promise<void>;
}) {
  if (!profiles.length) return <Empty text="正在读取模型档案。" />;
  return (
    <div className="model-profile-grid">
      {profiles.map((profile) => (
        <LocalizedModelProfileEditor
          key={profile.role} profile={profile}
          test={tests[profile.role]} busy={busy}
          onSave={onSave} onTest={onTest}
        />
      ))}
    </div>
  );
}

// ─── Settings Extras (theme, API keys, CLI paths) ───────────────────────────

type SettingsMetadata = Record<string, { value?: string; configured?: boolean }>;

function SettingsExtras({ busy }: { busy: boolean }) {
  const [metadata, setMetadata] = useState<SettingsMetadata>({});
  const [theme, setTheme] = useState<ThemePreset>("bright");
  const [custom, setCustom] = useState<ThemeColors>({ background: "#c7e6c9", text: "#1e3524", accent: "#2e7d32" });
  const [imageKey, setImageKey] = useState("");
  const [imageBaseUrl, setImageBaseUrl] = useState("https://api.openai.com/v1");
  const [imageModel, setImageModel] = useState("gpt-image-1.5");
  const [claudeBin, setClaudeBin] = useState("");
  const [codexBin, setCodexBin] = useState("");
  const [dataDir, setDataDir] = useState("");
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState("");

  const getValue = (settings: SettingsMetadata, key: string, fallback = "") =>
    typeof settings[key]?.value === "string" ? settings[key].value! : fallback;
  const load = async () => {
    const [settings, dataLocation] = await Promise.all([
      api<SettingsMetadata>("/api/settings"),
      api<{ data_dir: string; selected_data_dir?: string }>("/api/settings/data-dir"),
    ]);
    setMetadata(settings);
    const nextTheme = getValue(settings, "theme_preset", "bright") as ThemePreset;
    const validTheme = ["warm", "bright", "bean", "custom"].includes(nextTheme) ? nextTheme : "bright";
    const nextCustom = {
      background: safeThemeColor(getValue(settings, "theme_background", "#c7e6c9"), "#c7e6c9"),
      text: safeThemeColor(getValue(settings, "theme_text", "#1e3524"), "#1e3524"),
      accent: safeThemeColor(getValue(settings, "theme_accent", "#2e7d32"), "#2e7d32"),
    };
    setTheme(validTheme);
    setCustom(nextCustom);
    setImageBaseUrl(getValue(settings, "gpt_image_base_url", "https://api.openai.com/v1"));
    setImageModel(getValue(settings, "gpt_image_model_id", "gpt-image-1.5"));
    setClaudeBin(getValue(settings, "claude_bin"));
    setCodexBin(getValue(settings, "codex_bin"));
    setDataDir(dataLocation.selected_data_dir || dataLocation.data_dir);
    applyTheme(validTheme, nextCustom);
  };
  useEffect(() => {
    load().catch((e) => setMessage(e instanceof Error ? e.message : String(e)));
  }, []);
  const previewTheme = (preset: ThemePreset, colors = custom) => {
    setTheme(preset);
    applyTheme(preset, colors);
  };
  const updateCustom = (key: keyof ThemeColors, color: string) => {
    const next = { ...custom, [key]: color };
    setCustom(next);
    if (theme === "custom") applyTheme("custom", next);
  };
  const detectClaude = async () => {
    setMessage("");
    try {
      const result = await api<{ detected: boolean; path?: string }>("/api/settings/detect-claude");
      if (result.detected && result.path) { setClaudeBin(result.path); setMessage("已检测到 Claude CLI。保存配置后生效。"); }
      else setMessage("未检测到 Claude CLI；使用 Responses 执行协议时不需要该路径。");
    } catch (e) { setMessage(e instanceof Error ? e.message : String(e)); }
  };
  const detectCodex = async () => {
    setMessage("");
    try {
      const result = await api<{ detected: boolean; path?: string }>("/api/settings/detect-codex");
      if (result.detected && result.path) { setCodexBin(result.path); setMessage("已检测到 Codex CLI。保存配置后生效。"); }
      else setMessage("未检测到主机 Codex CLI；安装版仍可使用内置运行时中的 Codex 适配器。");
    } catch (e) { setMessage(e instanceof Error ? e.message : String(e)); }
  };
  const chooseDataDirectory = async () => {
    setMessage("");
    const chooser = window.electronAPI?.selectDataDirectory;
    if (!chooser) { setMessage("数据目录选择仅在桌面版可用。"); return; }
    const selected = await chooser();
    if (!selected.canceled && selected.path) {
      setDataDir(selected.path);
      setMessage("新目录将在重启桌面应用后生效；旧工作流不会自动迁移，请手动复制 workspaces。");
    }
  };
  const save = async () => {
    setSaving(true);
    setMessage("");
    try {
      const settings: Record<string, string> = {
        theme_preset: theme, theme_background: custom.background, theme_text: custom.text,
        theme_accent: custom.accent, gpt_image_base_url: imageBaseUrl.trim(),
        gpt_image_model_id: imageModel.trim(), claude_bin: claudeBin.trim(), codex_bin: codexBin.trim(),
      };
      if (imageKey.trim()) settings.gpt_image_api_key = imageKey.trim();
      if (dataDir.trim())
        await api("/api/settings/data-dir", { method: "PUT", body: JSON.stringify({ data_dir: dataDir.trim() }) });
      await api<{ ok: boolean }>("/api/settings", { method: "PUT", body: JSON.stringify({ settings }) });
      window.localStorage.setItem("vibe-theme-preset", theme);
      window.localStorage.setItem("vibe-theme-custom", JSON.stringify(custom));
      applyTheme(theme, custom);
      setImageKey("");
      await load();
      setMessage("配置已安全保存。API 密钥不会回显到界面或 SQLite。");
    } catch (e) { setMessage(e instanceof Error ? e.message : String(e)); }
    finally { setSaving(false); }
  };
  return (
    <section className="settings-section settings-extras">
      <div className="section-command">
        <div><p className="eyebrow">界面与本机能力</p><h3>主题和其他配置</h3></div>
        <button type="button" className="quiet" disabled={busy || saving} onClick={() => load().catch(() => {})}>重新读取</button>
      </div>
      <div className="settings-extra-grid">
        <article className="settings-extra-card">
          <h4>主题</h4>
          <div className="theme-options" role="radiogroup" aria-label="界面主题">
            {(([["warm", "暖色"], ["bright", "亮白"], ["bean", "豆沙绿"], ["custom", "自定义"]] as Array<[ThemePreset, string]>)).map(([key, label]) => (
              <button key={key} type="button" role="radio" aria-checked={theme === key}
                className={`quiet theme-option${theme === key ? " selected" : ""}`}
                onClick={() => previewTheme(key)}>{label}</button>
            ))}
          </div>
          {theme === "custom" && (
            <div className="theme-color-grid">
              <label>背景色<input type="color" value={custom.background} onChange={(e) => updateCustom("background", e.target.value)} /></label>
              <label>文字色<input type="color" value={custom.text} onChange={(e) => updateCustom("text", e.target.value)} /></label>
              <label>强调色<input type="color" value={custom.accent} onChange={(e) => updateCustom("accent", e.target.value)} /></label>
            </div>
          )}
        </article>
        <article className="settings-extra-card">
          <h4>GPT Image</h4>
          <label>API Key<input type="password" autoComplete="new-password" value={imageKey}
            onChange={(e) => setImageKey(e.target.value)}
            placeholder={metadata.gpt_image_api_key?.configured ? "已配置；留空保持不变" : "sk-…"} /></label>
          <label>Base URL<input value={imageBaseUrl} onChange={(e) => setImageBaseUrl(e.target.value)} /></label>
          <label>Model ID<input value={imageModel} onChange={(e) => setImageModel(e.target.value)} /></label>
        </article>
        <article className="settings-extra-card">
          <h4>Claude CLI</h4>
          <label>可执行文件路径<input value={claudeBin} onChange={(e) => setClaudeBin(e.target.value)} placeholder="自动探测或填写 claude.exe 路径" /></label>
          <button type="button" className="quiet" disabled={busy || saving} onClick={detectClaude}>自动探测</button>
          <small>执行者使用 Anthropic 消息协议时调用；Responses 协议使用内置工作区执行器。</small>
        </article>
        <article className="settings-extra-card">
          <h4>Codex CLI</h4>
          <label>可执行文件路径<input value={codexBin} onChange={(e) => setCodexBin(e.target.value)} placeholder="自动探测或填写 codex.exe 路径" /></label>
          <button type="button" className="quiet" disabled={busy || saving} onClick={detectCodex}>自动探测</button>
          <small>覆盖主机/PATH 探测结果。安装版优先使用经清单校验的内置 Codex。</small>
        </article>
        <article className="settings-extra-card">
          <h4>数据存储位置</h4>
          <label>目录<input value={dataDir} readOnly placeholder="使用桌面应用默认目录" /></label>
          <button type="button" className="quiet" disabled={busy || saving} onClick={chooseDataDirectory}>选择新位置</button>
          <small>更改后需重启；旧工作流不会自动迁移，请手动复制 workspaces。</small>
        </article>
      </div>
      {message && (
        <p className={`settings-message${message.includes("保存") || message.includes("检测到") ? " success" : ""}`}>{message}</p>
      )}
      <div className="workflow-config-actions settings-save-actions">
        <button type="button" disabled={busy || saving} onClick={save}>{saving ? "保存中…" : "保存配置"}</button>
      </div>
    </section>
  );
}

// ─── Settings connection props ───────────────────────────────────────────────

export type SettingsConnectionProps = {
  busy: boolean;
  doctor?: Record<string, unknown>;
  agentManifest?: Record<string, unknown>;
  project?: Project;
  agentAdapter: string;
  agentPrompt: string;
  agentTasks: AgentTask[];
  collabGoal?: string;
  collaborations?: AgentCollaboration[];
  modelProfiles: ModelProfile[];
  modelProfileTests: Record<string, ModelProfileTest>;
  onReloadDoctor: () => Promise<void>;
  onReloadAgents: () => Promise<void>;
  onAdapterChange: (value: string) => void;
  onPromptChange: (value: string) => void;
  onLaunchAgent: () => Promise<void>;
  onReloadTasks: () => Promise<void>;
  onCancelAgent: (id: string) => Promise<void>;
  onRetryAgent: (id: string) => Promise<void>;
  onCollabGoalChange?: (value: string) => void;
  onLaunchCollaboration?: () => Promise<void>;
  onReloadCollaborations?: () => Promise<void>;
  onReloadProfiles: () => Promise<void>;
  onSaveProfile: (role: ModelProfile["role"], value: ModelProfileUpdate) => Promise<void>;
  onTestProfile: (role: ModelProfile["role"]) => Promise<void>;
};

// ─── Main export ─────────────────────────────────────────────────────────────

export function SettingsConnection({
  busy, doctor, agentManifest, project, agentAdapter, agentPrompt,
  agentTasks, collabGoal, collaborations, modelProfiles, modelProfileTests,
  onReloadDoctor, onReloadAgents, onAdapterChange, onPromptChange,
  onLaunchAgent, onReloadTasks, onCancelAgent, onRetryAgent,
  onCollabGoalChange = () => undefined,
  onLaunchCollaboration = async () => undefined,
  onReloadCollaborations = async () => undefined,
  onReloadProfiles, onSaveProfile, onTestProfile,
}: SettingsConnectionProps) {
  const collabGoalValue = collabGoal ?? "";
  const collaborationItems = collaborations ?? [];
  return (
    <Panel title="设置与连接" detail="">
      <section className="settings-section">
        <div className="section-command">
          <h3>模型档案</h3>
          <button className="icon-button quiet" type="button" title="重新读取模型档案"
            aria-label="重新读取模型档案" disabled={busy} onClick={onReloadProfiles}>↻</button>
        </div>
        <ModelProfiles profiles={modelProfiles} tests={modelProfileTests} busy={busy}
          onSave={onSaveProfile} onTest={onTestProfile} />
      </section>
      <SettingsExtras busy={busy} />
      <section className="settings-section">
        <div className="section-command">
          <h3>环境诊断</h3>
          <button className="icon-button quiet" type="button" title="重新检测环境"
            aria-label="重新检测环境" disabled={busy} onClick={onReloadDoctor}>↻</button>
        </div>
        <div className="diagnostics">
          <article>{doctor ? <JsonCard value={doctor} /> : <Empty text="正在读取本机环境。" />}</article>
          <article>
            <div className="section-command">
              <h3>智能体适配器</h3>
              <button className="icon-button quiet" type="button" title="刷新智能体适配器"
                aria-label="刷新智能体适配器" disabled={busy} onClick={onReloadAgents}>↻</button>
            </div>
            {agentManifest ? <JsonCard value={agentManifest} /> : <Empty text="正在读取智能体适配器清单。" />}
          </article>
        </div>
      </section>
      <section className="settings-section">
        <h3>智能体任务</h3>
        <div className="form-grid">
          <label>
            智能体运行器
            <select value={agentAdapter} onChange={(e) => onAdapterChange(e.target.value)}>
              <option value="codex">Codex CLI</option>
              <option value="claude">Claude Code</option>
            </select>
          </label>
          <Field label="任务要求" value={agentPrompt} set={onPromptChange} area placeholder="描述一个只读、可审计的项目任务" />
        </div>
        <div className="actions">
          <button disabled={busy || !project || !agentPrompt.trim()} onClick={onLaunchAgent}>
            启动只读智能体任务
          </button>
          <button className="quiet" disabled={busy || !project} onClick={onReloadTasks}>
            恢复任务历史
          </button>
        </div>
        {agentTasks.length ? (
          <ol className="results">
            {agentTasks.map((item) => (
              <li key={item.id}>
                <b>{item.adapter} · {statusText(item.status)}</b>
                <span>{item.prompt}</span>
                {item.result.final_text && <pre className="json-card">{item.result.final_text}</pre>}
                {item.failure_reason && <small>{item.failure_reason}</small>}
                <span>生命周期事件 {item.events.length} 条 · CLI 结构化事件 {item.result.structured_events?.length || 0} 条 · 审计文件 {item.audit_path || "等待生成"}</span>
                {item.result.artifact_sha256 && (
                  <span>响应产物 SHA256 {item.result.artifact_sha256} · {item.result.artifact_path}</span>
                )}
                <div className="inline-actions">
                  <button className="danger" disabled={busy || !item.cancellable} onClick={() => onCancelAgent(item.id)}>取消</button>
                  <button className="quiet" disabled={busy || !["failed", "cancelled", "interrupted"].includes(item.status)} onClick={() => onRetryAgent(item.id)}>重试</button>
                </div>
              </li>
            ))}
          </ol>
        ) : (
          <Empty text={project ? "尚无智能体任务。" : "请先创建研究合同。"} />
        )}
      </section>
      <section className="settings-section">
        <h3>多 Agent 协作</h3>
        <p className="muted">按执行模型 → 独立审稿模型 → 科研编辑模型顺序真实调用已配置的 Provider/CLI；无密钥时诚实失败并持久化协作报告，不静默降级为成功。</p>
        <div className="form-grid">
          <Field label="协作目标" value={collabGoalValue} set={onCollabGoalChange} area placeholder="描述需要多角色协作的研究目标" />
        </div>
        <div className="actions">
          <button disabled={busy || !project || !collabGoalValue.trim()} onClick={onLaunchCollaboration}>
            启动多 Agent 协作
          </button>
          <button className="quiet" disabled={busy || !project} onClick={onReloadCollaborations}>
            刷新协作历史
          </button>
        </div>
        {collaborationItems.length ? (
          <ol className="results">
            {collaborationItems.map((item) => (
              <li key={item.id}>
                <b>{statusText(item.status)} · {item.roles.join(" / ")}</b>
                <span>{item.goal}</span>
                {item.failure_reason && <small>{item.failure_reason}</small>}
                <span>步骤 {item.steps.length} · 报告 {item.report_path || "等待生成"}</span>
                {item.report_sha256 && <span>报告 SHA256 {item.report_sha256}</span>}
                <ul>
                  {item.steps.map((step, i) => (
                    <li key={`${item.id}-${step.role}-${i}`}>
                      {step.role}: {statusText(step.status)}
                      {step.error ? ` · ${step.error}` : ""}
                      {step.output_sha256 ? ` · out ${step.output_sha256.slice(0, 12)}` : ""}
                    </li>
                  ))}
                </ul>
              </li>
            ))}
          </ol>
        ) : (
          <Empty text={project ? "尚无多 Agent 协作记录。" : "请先创建研究合同。"} />
        )}
      </section>
    </Panel>
  );
}

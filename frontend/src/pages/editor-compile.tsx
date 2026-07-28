import React, { useState, useEffect } from "react";
import { api, download, type Workflow } from "../api";
import { Panel, Empty, Field } from "../ui";

// ─── Local types ─────────────────────────────────────────────────────────────

type EditorWorkspaceFile = { path: string; size: number };
type EditorCompileResult = {
  status: string;
  source: { path: string; sha256: string };
  outputs: Array<{ path: string; sha256: string; bytes: number }>;
  manifest: { path: string; sha256: string };
  failure_reason?: string;
  stderr: string;
};
type EditorDocxStatus = {
  status: string;
  documents: Array<{ path: string; sha256: string; bytes: number }>;
  latest_compile?: { status: string; stderr?: string; failure_reason?: string };
};
type ImageAuditEntry = {
  source: { path: string; sha256: string; bytes: number };
  status: string;
  format?: string;
  width?: number;
  height?: number;
  mode?: string;
  frames?: number;
  warnings: string[];
  failure_reason?: string;
};
type ImageAuditResult = {
  status: string;
  scope: string;
  summary: { files_scanned: number; valid: number; failed: number };
  images: ImageAuditEntry[];
  manifest: { path: string; sha256: string };
};
type ImageDescriptionResult = ImageAuditResult & {
  image: ImageAuditEntry;
  description: string;
  description_kind: string;
};
type GeneratedImageResult = {
  status: string;
  image?: ImageAuditEntry;
  manifest: { path: string; sha256: string };
  failure_reason?: string;
  revised_prompt?: string;
};
type ProjectPreviewProcess = {
  port: number;
  url: string;
  running: boolean;
};
type ProjectPreviewStatus = {
  wf_id: string;
  frontend: ProjectPreviewProcess | null;
  backend: ProjectPreviewProcess | null;
};
type ProjectPreviewStart = {
  wf_id: string;
  servers: Array<{
    kind: "frontend" | "backend";
    status: string;
    port?: number;
    url?: string;
    note?: string;
    error?: string;
  }>;
};
type EditorAgentProposal = {
  id: string;
  path: string;
  base_hash: string;
  content: string;
  proposed_diff: string;
  status: string;
};
type EditorAgentResult = {
  status: string;
  summary?: string;
  task_id?: string;
  changed_files?: string[];
  proposals?: EditorAgentProposal[];
  has_diff?: boolean;
  proposal?: EditorAgentProposal | null;
  failure_reason?: string;
};
type EditorChatTurn = {
  id?: string;
  role?: string;
  request?: string;
  file?: string;
  content?: string;
  created_at?: string;
};
type EditorAiEditResult = {
  content: string;
  file: string;
  message: string;
  role?: string;
  status?: string;
  history?: EditorChatTurn[];
  history_path?: string;
};
type EditorScriptResult = {
  success: boolean;
  returncode: number;
  stdout: string;
  stderr: string;
  language: string;
  started_at?: string;
  finished_at?: string;
  audit?: { path: string; sha256: string };
};
export function EditorCompilePage({
  workflows,
  selectedId,
  onSelected,
  busy,
  onRun,
}: {
  workflows: Workflow[];
  selectedId: string;
  onSelected: (id: string) => void;
  busy: boolean;
  onRun: (action: () => Promise<void>) => Promise<void>;
}) {
  const [files, setFiles] = useState<EditorWorkspaceFile[]>([]),
    [path, setPath] = useState(""),
    [content, setContent] = useState(""),
    [compile, setCompile] = useState<EditorCompileResult>(),
    [docx, setDocx] = useState<EditorDocxStatus>(),
    [imagePath, setImagePath] = useState(""),
    [imageAudit, setImageAudit] = useState<ImageAuditResult>(),
    [imageDescription, setImageDescription] =
      useState<ImageDescriptionResult>(),
    [generationPrompt, setGenerationPrompt] = useState(""),
    [generationModel, setGenerationModel] = useState("gpt-image-1"),
    [generationSize, setGenerationSize] = useState("1024x1024"),
    [generatedImage, setGeneratedImage] = useState<GeneratedImageResult>(),
    [previewMode, setPreviewMode] = useState<"frontend" | "backend" | "both">("both"),
    [preview, setPreview] = useState<ProjectPreviewStatus>(),
    [previewMessage, setPreviewMessage] = useState(""),
    [agentPrompt, setAgentPrompt] = useState(""),
    [agentResult, setAgentResult] = useState<EditorAgentResult>(),
    [agentMessage, setAgentMessage] = useState(""),
    [editPrompt, setEditPrompt] = useState(""),
    [editResult, setEditResult] = useState<EditorAiEditResult>(),
    [editMessage, setEditMessage] = useState(""),
    [chatHistory, setChatHistory] = useState<EditorChatTurn[]>([]),
    [scriptLanguage, setScriptLanguage] = useState<"python" | "bash" | "node">("python"),
    [scriptSource, setScriptSource] = useState('print("VIBE_SCRIPT_OK")\n'),
    [scriptResult, setScriptResult] = useState<EditorScriptResult>(),
    [scriptMessage, setScriptMessage] = useState("");
  const load = async () => {
    if (!selectedId) {
      setFiles([]);
      setPath("");
      setContent("");
      setCompile(undefined);
      setDocx(undefined);
      setPreview(undefined);
      setPreviewMessage("");
      setAgentResult(undefined);
      setAgentMessage("");
      setEditResult(undefined);
      setEditMessage("");
      setChatHistory([]);
      setScriptResult(undefined);
      setScriptMessage("");
      return;
    }
    const listed = await api<{ files: EditorWorkspaceFile[] }>(
      `/api/editor/${selectedId}/files`,
    );
    setFiles(listed.files);
    const preferred =
      listed.files.find((item) => item.path === path) ||
      listed.files.find((item) => item.path === "paper/main.md") ||
      listed.files.find((item) => /\.(md|tex)$/i.test(item.path));
    if (preferred) {
      setPath(preferred.path);
      const value = await api<{ content: string }>(
        `/api/editor/${selectedId}/file?path=${encodeURIComponent(preferred.path)}`,
      );
      setContent(value.content);
    } else {
      setPath("");
      setContent("");
    }
    setDocx(
      await api<EditorDocxStatus>(`/api/editor/${selectedId}/docx-status`),
    );
    try {
      setPreview(
        await api<ProjectPreviewStatus>(`/api/editor/${selectedId}/serve/status`),
      );
    } catch {
      setPreview(undefined);
    }
    try {
      const staged = await api<EditorAgentResult>(
        `/api/editor/${selectedId}/ai-agent-check`,
      );
      setAgentResult(staged.has_diff ? staged : undefined);
    } catch {
      /* staged proposals are optional during workspace refresh */
    }
    try {
      const history = await api<{ history: EditorChatTurn[] }>(
        `/api/editor/${selectedId}/chat-history`,
      );
      setChatHistory(history.history || []);
    } catch {
      setChatHistory([]);
    }
  };
  useEffect(() => {
    setImagePath("");
    setImageAudit(undefined);
    setImageDescription(undefined);
    setGeneratedImage(undefined);
    setAgentResult(undefined);
    setAgentMessage("");
    setEditResult(undefined);
    setEditMessage("");
    setChatHistory([]);
    setScriptResult(undefined);
    setScriptMessage("");
    void load();
  }, [selectedId]);
  const open = (next: string) =>
    onRun(async () => {
      setPath(next);
      setContent(
        (
          await api<{ content: string }>(
            `/api/editor/${selectedId}/file?path=${encodeURIComponent(next)}`,
          )
        ).content,
      );
    });
  const save = () =>
    onRun(async () => {
      if (!path) throw new Error("请选择 Markdown 或 LaTeX 源文件");
      await api(`/api/editor/${selectedId}/file`, {
        method: "PUT",
        body: JSON.stringify({ path, content }),
      });
      await load();
    });
  const runCompile = () =>
    onRun(async () => {
      if (!selectedId) throw new Error("请选择工作流");
      const result = await api<EditorCompileResult>(
        `/api/editor/${selectedId}/compile`,
        {
          method: "POST",
          body: JSON.stringify({
            source_md: path.endsWith(".md") ? content : "",
          }),
        },
      );
      setCompile(result);
      setDocx(
        await api<EditorDocxStatus>(`/api/editor/${selectedId}/docx-status`),
      );
      await load();
    });
  const runImageAudit = () =>
    onRun(async () => {
      if (!selectedId) throw new Error("请选择工作流");
      const query = imagePath ? `?path=${encodeURIComponent(imagePath)}` : "";
      setImageAudit(
        await api<ImageAuditResult>(
          `/api/editor/${selectedId}/image-check${query}`,
        ),
      );
      setImageDescription(undefined);
    });
  const describeImage = () =>
    onRun(async () => {
      if (!selectedId || !imagePath) throw new Error("请选择图像文件");
      const result = await api<ImageDescriptionResult>(
        `/api/editor/${selectedId}/describe-image?path=${encodeURIComponent(imagePath)}`,
        { method: "POST" },
      );
      setImageAudit(result);
      setImageDescription(result);
    });
  const generateImage = () =>
    onRun(async () => {
      if (!selectedId || !generationPrompt.trim())
        throw new Error("请输入图像生成提示");
      const result = await api<GeneratedImageResult>(
        `/api/editor/${selectedId}/generate-image`,
        {
          method: "POST",
          body: JSON.stringify({
            prompt: generationPrompt,
            model: generationModel,
            size: generationSize,
          }),
        },
      );
      setGeneratedImage(result);
      await load();
    });
  const refreshPreview = () =>
    onRun(async () => {
      setPreview(
        await api<ProjectPreviewStatus>(`/api/editor/${selectedId}/serve/status`),
      );
    });
  const startPreview = () =>
    onRun(async () => {
      const started = await api<ProjectPreviewStart>(
        `/api/editor/${selectedId}/serve`,
        { method: "POST", body: JSON.stringify({ mode: previewMode }) },
      );
      const failures = started.servers.filter((item) => item.status === "error");
      setPreviewMessage(
        failures.length
          ? failures.map((item) => item.error || `${item.kind} 启动失败`).join("；")
          : started.servers.map((item) => item.note).filter(Boolean).join("；") || "项目预览已启动。",
      );
      setPreview(
        await api<ProjectPreviewStatus>(`/api/editor/${selectedId}/serve/status`),
      );
    });
  const stopPreview = () =>
    onRun(async () => {
      await api(`/api/editor/${selectedId}/serve`, { method: "DELETE" });
      setPreviewMessage("项目预览已停止。");
      setPreview(
        await api<ProjectPreviewStatus>(`/api/editor/${selectedId}/serve/status`),
      );
    });
  const openPreview = (url: string) => {
    window.open(url, "_blank", "noopener,noreferrer");
    setPreviewMessage(`正在系统浏览器中打开 ${url}`);
  };
  const runEditorAgent = () =>
    onRun(async () => {
      if (!selectedId || !agentPrompt.trim()) {
        throw new Error("请输入编辑代理指令");
      }
      setAgentMessage("");
      try {
        const result = await api<EditorAgentResult>(
          `/api/editor/${selectedId}/ai-agent`,
          {
            method: "POST",
            body: JSON.stringify({ message: agentPrompt.trim() }),
          },
        );
        setAgentResult(result);
        setAgentMessage(
          result.status === "staged"
            ? `已暂存 ${result.changed_files?.length || 0} 个可审阅修改`
            : result.summary || "代理未提出文件修改",
        );
      } catch (error) {
        const detail = error instanceof Error ? error.message : String(error);
        if (detail.includes("agent_provider_unavailable") || detail.includes("501")) {
          setAgentMessage(
            "编辑代理不可用：请先在设置中配置科研编辑模型的 Base URL 与 API 密钥。",
          );
          setAgentResult(undefined);
          return;
        }
        throw error;
      }
    });
  const applyEditorAgent = () =>
    onRun(async () => {
      if (!selectedId) throw new Error("请选择工作流");
      const proposal =
        agentResult?.proposal ||
        agentResult?.proposals?.[0] ||
        null;
      const filesToApply = proposal?.path
        ? [proposal.path]
        : agentResult?.changed_files || [];
      await api(`/api/editor/${selectedId}/ai-agent-apply`, {
        method: "POST",
        body: JSON.stringify({ files: filesToApply }),
      });
      setAgentMessage(
        proposal?.path
          ? `已应用 ${proposal.path}，可撤销到备份版本。`
          : "已应用暂存提案。",
      );
      setAgentResult(undefined);
      await load();
    });
  const discardEditorAgent = () =>
    onRun(async () => {
      if (!selectedId) throw new Error("请选择工作流");
      await api(`/api/editor/${selectedId}/ai-agent-discard`, {
        method: "POST",
      });
      setAgentResult(undefined);
      setAgentMessage("已丢弃暂存提案。");
    });
  const undoEditorAgent = () =>
    onRun(async () => {
      if (!selectedId) throw new Error("请选择工作流");
      await api(`/api/editor/${selectedId}/ai-agent-undo`, { method: "POST" });
      setAgentMessage("已撤销最近一次代理应用。");
      await load();
    });
  const runAiEdit = () =>
    onRun(async () => {
      if (!selectedId || !path) throw new Error("请先选择源文件");
      if (!editPrompt.trim()) throw new Error("请输入 AI 编辑指令");
      setEditMessage("");
      try {
        const result = await api<EditorAiEditResult>(
          `/api/editor/${selectedId}/ai-edit`,
          {
            method: "POST",
            body: JSON.stringify({
              message: editPrompt.trim(),
              current_file: path,
              current_content: content,
              workspace_files: files.map((item) => item.path),
              role: path.endsWith(".tex") ? "latex" : "markdown",
              history: chatHistory,
            }),
          },
        );
        setEditResult(result);
        if (result.history) setChatHistory(result.history);
        setEditMessage(
          result.history_path
            ? `已生成建议内容，聊天记录已写入 ${result.history_path}`
            : "已生成建议内容，可审阅后写入当前文件。",
        );
      } catch (error) {
        const detail = error instanceof Error ? error.message : String(error);
        if (
          detail.includes("agent_provider_unavailable") ||
          detail.includes("501")
        ) {
          setEditMessage(
            "AI 编辑不可用：请先在设置中配置科研编辑模型的 Base URL 与 API 密钥。",
          );
          setEditResult(undefined);
          return;
        }
        throw error;
      }
    });
  const applyAiEdit = () => {
    if (!editResult?.content) throw new Error("没有可应用的 AI 编辑结果");
    setContent(editResult.content);
    setEditMessage(`已把建议内容写入编辑器缓冲区：${editResult.file || path}`);
  };
  const clearChatHistory = () =>
    onRun(async () => {
      if (!selectedId) throw new Error("请选择工作流");
      await api(`/api/editor/${selectedId}/chat-history`, { method: "DELETE" });
      setChatHistory([]);
      setEditMessage("已清空编辑器聊天历史。");
    });
  const runWorkspaceScript = () =>
    onRun(async () => {
      if (!selectedId) throw new Error("请选择工作流");
      if (!scriptSource.trim()) throw new Error("请输入脚本内容");
      const result = await api<EditorScriptResult>(
        `/api/editor/${selectedId}/run-script`,
        {
          method: "POST",
          body: JSON.stringify({
            script: scriptSource,
            language: scriptLanguage,
          }),
        },
      );
      setScriptResult(result);
      setScriptMessage(
        result.success
          ? `脚本执行成功（exit ${result.returncode}）${
              result.audit ? ` · 审计 ${result.audit.path}` : ""
            }`
          : `脚本执行失败（exit ${result.returncode}）`,
      );
    });
  const imageFiles = files.filter((item) =>
    /\.(avif|bmp|gif|ico|jpe?g|png|tiff?|webp)$/i.test(item.path),
  );
  const hasProjectFiles = files.some((item) => item.path.startsWith("code/"));
  const stagedProposal =
    agentResult?.proposal || agentResult?.proposals?.[0] || null;
  if (!workflows.length)
    return (
      <Panel
        title="编辑与编译"
        detail="以工作区内的 Markdown 或 LaTeX 源文件生成可下载、可审计的 DOCX 和 HTML 产物。"
      >
        <Empty text="先创建一个工作流，再进入编辑与编译。" />
      </Panel>
    );
  return (
    <Panel
      title="编辑与编译"
      detail="Pandoc 在本地受限工作区运行；每次编译保存源文件、运行时、输出哈希和失败日志，不会把缺少 TeX 的情形伪装成 PDF 成功。"
    >
      <section className="settings-section">
        <div className="form-grid">
          <label>
            工作流
            <select
              value={selectedId}
              onChange={(event) => onSelected(event.target.value)}
            >
              {workflows.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.title}
                </option>
              ))}
            </select>
          </label>
          <label>
            源文件
            <select
              value={path}
              onChange={(event) => void open(event.target.value)}
            >
              <option value="">选择 Markdown 或 LaTeX</option>
              {files
                .filter((item) => /\.(md|tex)$/i.test(item.path))
                .map((item) => (
                  <option key={item.path} value={item.path}>
                    {item.path}
                  </option>
                ))}
            </select>
          </label>
        </div>
        <div className="actions">
          <button
            className="quiet"
            disabled={busy}
            onClick={() => void onRun(load)}
          >
            刷新工作区
          </button>
          <button disabled={busy || !path} onClick={save}>
            保存源文件
          </button>
          <button
            disabled={
              busy ||
              (!path && !files.some((item) => /\.(md|tex)$/i.test(item.path)))
            }
            onClick={runCompile}
          >
            编译 DOCX 与 HTML
          </button>
          {docx?.documents?.[0] && (
            <button
              className="quiet"
              disabled={busy}
              onClick={() =>
                void onRun(() =>
                  download(
                    `/api/editor/${selectedId}/docx`,
                    "research-document.docx",
                  ),
                )
              }
            >
              下载 DOCX
            </button>
          )}
        </div>
        {path ? (
          <textarea
            aria-label="编辑器源文件"
            className="code-editor"
            value={content}
            onChange={(event) => setContent(event.target.value)}
          />
        ) : (
          <Empty text="工作区中尚无可编译的 Markdown 或 LaTeX 文件。" />
        )}
      </section>
      <section className="settings-section">
        <h3>编辑代理</h3>
        <p>
          使用设置中的科研编辑模型生成可审阅文件提案。未配置密钥时明确提示，不会伪造成功。
        </p>
        <Field
          label="代理指令"
          value={agentPrompt}
          set={setAgentPrompt}
          placeholder="例如：收紧摘要，并统一图表编号"
          area
        />
        <div className="actions">
          <button
            disabled={busy || !selectedId || !agentPrompt.trim()}
            onClick={runEditorAgent}
          >
            生成提案
          </button>
          <button
            className="quiet"
            disabled={busy || !selectedId || !stagedProposal}
            onClick={applyEditorAgent}
          >
            应用提案
          </button>
          <button
            className="quiet"
            disabled={busy || !selectedId || !stagedProposal}
            onClick={discardEditorAgent}
          >
            丢弃提案
          </button>
          <button
            className="quiet"
            disabled={busy || !selectedId}
            onClick={undoEditorAgent}
          >
            撤销最近应用
          </button>
        </div>
        {agentMessage && <p className="file-path">{agentMessage}</p>}
        {stagedProposal && (
          <>
            <div
              className={
                "graph-gate " +
                (agentResult?.status === "staged" || stagedProposal.status === "staged"
                  ? "passed"
                  : "blocked")
              }
            >
              <b>
                {agentResult?.summary || "已暂存可审阅修改"}
              </b>
              <span>{stagedProposal.path}</span>
              <code>{stagedProposal.base_hash.slice(0, 16)}</code>
            </div>
            <textarea
              aria-label="编辑代理提案 diff"
              className="code-editor"
              readOnly
              value={stagedProposal.proposed_diff}
            />
          </>
        )}
      </section>
      <section className="settings-section">
        <h3>AI 编辑与聊天历史</h3>
        <p>
          对当前源文件发起定向改写；结果写入 `_chat_history.json`，可审阅后再覆盖编辑器内容。
        </p>
        <Field
          label="编辑指令"
          value={editPrompt}
          set={setEditPrompt}
          placeholder="例如：把摘要压缩到 150 词，并补上贡献列表"
          area
        />
        <div className="actions">
          <button
            disabled={busy || !selectedId || !path || !editPrompt.trim()}
            onClick={runAiEdit}
          >
            生成 AI 编辑
          </button>
          <button
            className="quiet"
            disabled={busy || !editResult?.content}
            onClick={applyAiEdit}
          >
            写入编辑器
          </button>
          <button
            className="quiet"
            disabled={busy || !selectedId || chatHistory.length === 0}
            onClick={clearChatHistory}
          >
            清空聊天历史
          </button>
        </div>
        {editMessage && <p className="file-path">{editMessage}</p>}
        {editResult?.content && (
          <textarea
            aria-label="AI 编辑建议内容"
            className="code-editor"
            readOnly
            value={editResult.content}
          />
        )}
        {chatHistory.length > 0 && (
          <ol className="results">
            {chatHistory
              .slice()
              .reverse()
              .slice(0, 8)
              .map((item, index) => (
                <li key={item.id || `${item.created_at || "turn"}-${index}`}>
                  <b>{item.file || path || "workspace"}</b>
                  <span>{item.request || item.role || "assistant"}</span>
                  <code>
                    {(item.content || "").slice(0, 160)}
                    {(item.content || "").length > 160 ? "…" : ""}
                  </code>
                </li>
              ))}
          </ol>
        )}
      </section>
      <section className="settings-section">
        <h3>工作区脚本执行</h3>
        <p>
          在受限监督器中运行 python / bash / node；每次执行写入 `.editor_runs/` 审计记录，不静默吞错。
        </p>
        <div className="form-grid">
          <label>
            语言
            <select
              aria-label="脚本语言"
              value={scriptLanguage}
              onChange={(event) =>
                setScriptLanguage(event.target.value as "python" | "bash" | "node")
              }
            >
              <option value="python">Python</option>
              <option value="bash">Bash</option>
              <option value="node">Node</option>
            </select>
          </label>
        </div>
        <textarea
          aria-label="工作区脚本内容"
          className="code-editor"
          value={scriptSource}
          onChange={(event) => setScriptSource(event.target.value)}
        />
        <div className="actions">
          <button
            disabled={busy || !selectedId || !scriptSource.trim()}
            onClick={runWorkspaceScript}
          >
            运行脚本
          </button>
        </div>
        {scriptMessage && <p className="file-path">{scriptMessage}</p>}
        {scriptResult && (
          <>
            <div
              className={
                "graph-gate " + (scriptResult.success ? "passed" : "blocked")
              }
            >
              <b>
                {scriptResult.success ? "执行成功" : "执行失败"} · exit{" "}
                {scriptResult.returncode}
              </b>
              <span>{scriptResult.language}</span>
              {scriptResult.audit && (
                <code>
                  {scriptResult.audit.path} ·{" "}
                  {scriptResult.audit.sha256.slice(0, 16)}
                </code>
              )}
            </div>
            {(scriptResult.stdout || scriptResult.stderr) && (
              <textarea
                aria-label="脚本执行输出"
                className="code-editor"
                readOnly
                value={[
                  scriptResult.stdout
                    ? `STDOUT\n${scriptResult.stdout}`
                    : "",
                  scriptResult.stderr
                    ? `STDERR\n${scriptResult.stderr}`
                    : "",
                ]
                  .filter(Boolean)
                  .join("\n\n")}
              />
            )}
          </>
        )}
      </section>
      {hasProjectFiles && (
        <section className="settings-section">
          <h3>项目本地预览</h3>
          <p>自动识别静态页面、Vite、FastAPI、Flask 或 Express；前后端模式通过同源 /api 代理访问。</p>
          <div className="form-grid">
            <label>
              启动模式
              <select
                aria-label="项目预览启动模式"
                value={previewMode}
                onChange={(event) => setPreviewMode(event.target.value as "frontend" | "backend" | "both")}
              >
                <option value="both">前后端一起</option>
                <option value="frontend">仅前端</option>
                <option value="backend">仅后端</option>
              </select>
            </label>
          </div>
          <div className="actions">
            <button disabled={busy} onClick={startPreview}>启动项目预览</button>
            <button className="quiet" disabled={busy} onClick={refreshPreview}>刷新预览状态</button>
            <button
              className="quiet"
              disabled={busy || (!preview?.frontend && !preview?.backend)}
              onClick={stopPreview}
            >
              停止项目预览
            </button>
            {preview?.frontend?.running && (
              <button className="quiet" disabled={busy} onClick={() => openPreview(preview.frontend!.url)}>
                打开前端预览
              </button>
            )}
            {!preview?.frontend?.running && preview?.backend?.running && (
              <button className="quiet" disabled={busy} onClick={() => openPreview(preview.backend!.url)}>
                打开后端预览
              </button>
            )}
          </div>
          {(preview?.frontend || preview?.backend) && (
            <ol className="results">
              {(["frontend", "backend"] as const).map((kind) => {
                const process = preview[kind];
                return process ? (
                  <li key={kind}>
                    <b>{kind === "frontend" ? "前端" : "后端"} · 运行中</b>
                    <span>{process.url} · 端口 {process.port}</span>
                  </li>
                ) : null;
              })}
            </ol>
          )}
          {previewMessage && <p className="file-path">{previewMessage}</p>}
        </section>
      )}
      {compile && (
        <section className="settings-section">
          <h3>最近编译</h3>
          <div
            className={`graph-gate ${compile.status === "completed" ? "passed" : "blocked"}`}
          >
            <b>{compile.status === "completed" ? "编译完成" : "编译失败"}</b>
            <span>
              {compile.source.path} · {compile.source.sha256.slice(0, 16)}
            </span>
            <code>{compile.manifest.path}</code>
          </div>
          {compile.outputs.length ? (
            <ol className="results">
              {compile.outputs.map((item) => (
                <li key={item.path}>
                  <b>{item.path}</b>
                  <span>
                    {item.bytes} bytes · SHA256 {item.sha256}
                  </span>
                </li>
              ))}
            </ol>
          ) : null}
          {compile.failure_reason && (
            <p className="review-failure">{compile.failure_reason}</p>
          )}
          {compile.stderr && <pre className="json-card">{compile.stderr}</pre>}
        </section>
      )}
      {docx && (
        <section className="settings-section">
          <h3>DOCX 产物状态</h3>
          {docx.documents.length ? (
            <ol className="results">
              {docx.documents.map((item) => (
                <li key={item.path}>
                  <b>{item.path}</b>
                  <span>
                    {item.bytes} bytes · SHA256 {item.sha256}
                  </span>
                </li>
              ))}
            </ol>
          ) : (
            <Empty text="尚无 DOCX 产物。" />
          )}
        </section>
      )}
      <section className="settings-section">
        <h3>图像审计</h3>
        <div className="form-grid">
          <label>
            图像文件
            <select
              value={imagePath}
              onChange={(event) => setImagePath(event.target.value)}
            >
              <option value="">全部支持的图像</option>
              {imageFiles.map((item) => (
                <option key={item.path} value={item.path}>
                  {item.path}
                </option>
              ))}
            </select>
          </label>
        </div>
        <div className="actions">
          <button disabled={busy} onClick={runImageAudit}>
            {imagePath ? "审计所选图像" : "审计工作区图像"}
          </button>
          <button
            className="quiet"
            disabled={busy || !imagePath}
            onClick={describeImage}
          >
            读取元数据描述
          </button>
          {imageAudit && (
            <button
              className="quiet"
              disabled={busy}
              onClick={() =>
                void onRun(() =>
                  download(
                    `/api/editor/${selectedId}/download?path=${encodeURIComponent(imageAudit.manifest.path)}`,
                    "image-audit.json",
                  ),
                )
              }
            >
              下载审计清单
            </button>
          )}
        </div>
        {imageAudit && (
          <>
            <div
              className={`graph-gate ${imageAudit.status === "completed" ? "passed" : "blocked"}`}
            >
              <b>
                {imageAudit.status === "completed"
                  ? "审计通过"
                  : imageAudit.status === "no_images"
                    ? "未发现图像"
                    : "审计发现问题"}
              </b>
              <span>
                {imageAudit.summary.files_scanned} 个文件 · 有效{" "}
                {imageAudit.summary.valid} · 失败 {imageAudit.summary.failed}
              </span>
              <code>
                {imageAudit.manifest.path} ·{" "}
                {imageAudit.manifest.sha256.slice(0, 16)}
              </code>
            </div>
            {imageAudit.images.length ? (
              <ol className="results">
                {imageAudit.images.map((item) => (
                  <li key={item.source.path}>
                    <b>{item.source.path}</b>
                    <span>
                      {item.status === "valid"
                        ? `${item.format} · ${item.width}x${item.height} · ${item.mode} · SHA256 ${item.source.sha256}`
                        : item.failure_reason}
                    </span>
                    {item.warnings.length ? (
                      <small>{item.warnings.join(", ")}</small>
                    ) : null}
                  </li>
                ))}
              </ol>
            ) : (
              <Empty text="工作区中尚无受支持的图像文件。" />
            )}
            {imageDescription && (
              <p className="file-path">{imageDescription.description}</p>
            )}
          </>
        )}
      </section>
      <section className="settings-section">
        <h3>图像生成</h3>
        <div className="form-grid">
          <Field
            label="生成提示"
            value={generationPrompt}
            set={setGenerationPrompt}
            area
            placeholder="描述研究图示的对象、关系、标注和布局"
          />
          <Field
            label="模型"
            value={generationModel}
            set={setGenerationModel}
            placeholder="gpt-image-1"
          />
          <label>
            尺寸
            <select
              value={generationSize}
              onChange={(event) => setGenerationSize(event.target.value)}
            >
              <option value="1024x1024">1024 x 1024</option>
              <option value="1536x1024">1536 x 1024</option>
              <option value="1024x1536">1024 x 1536</option>
            </select>
          </label>
        </div>
        <div className="actions">
          <button
            disabled={busy || !generationPrompt.trim()}
            onClick={generateImage}
          >
            生成图像
          </button>
          {generatedImage?.image && (
            <button
              className="quiet"
              disabled={busy}
              onClick={() =>
                void onRun(() =>
                  download(
                    "/api/editor/" +
                      selectedId +
                      "/download?path=" +
                      encodeURIComponent(generatedImage.image!.source.path),
                    "generated-research-figure.png",
                  ),
                )
              }
            >
              下载生成图
            </button>
          )}
          {generatedImage && (
            <button
              className="quiet"
              disabled={busy}
              onClick={() =>
                void onRun(() =>
                  download(
                    "/api/editor/" +
                      selectedId +
                      "/download?path=" +
                      encodeURIComponent(generatedImage.manifest.path),
                    "image-generation-manifest.json",
                  ),
                )
              }
            >
              下载生成清单
            </button>
          )}
        </div>
        {generatedImage && (
          <>
            <div
              className={
                "graph-gate " +
                (generatedImage.status === "completed" ? "passed" : "blocked")
              }
            >
              <b>
                {generatedImage.status === "completed"
                  ? "生成完成"
                  : "生成失败"}
              </b>
              <span>
                {generatedImage.image
                  ? [
                      generatedImage.image.format,
                      generatedImage.image.width +
                        "x" +
                        generatedImage.image.height,
                      "SHA256 " + generatedImage.image.source.sha256,
                    ].join(" · ")
                  : generatedImage.failure_reason}
              </span>
              <code>
                {generatedImage.manifest.path} ·{" "}
                {generatedImage.manifest.sha256.slice(0, 16)}
              </code>
            </div>
            {generatedImage.revised_prompt && (
              <p className="file-path">{generatedImage.revised_prompt}</p>
            )}
          </>
        )}
      </section>
    </Panel>
  );
}

type DrawioExportResult = {
  status: string;
  source: { path: string; sha256: string; bytes: number };
  outputs: Array<{
    source: { path: string; sha256: string; bytes: number };
    status?: string;
    format?: string;
    width?: number;
    height?: number;
  }>;
  manifest: { path: string; sha256: string };
  failure_reason?: string;
  stderr?: string;
};
const DRAWIO_STARTER_XML =
  '<mxfile host="app.diagrams.net"><diagram name="Research flow"><mxGraphModel><root><mxCell id="0"/><mxCell id="1" parent="0"/><mxCell id="2" value="Research question" style="rounded=1;whiteSpace=wrap;html=1;" vertex="1" parent="1"><mxGeometry x="40" y="40" width="180" height="60" as="geometry"/></mxCell><mxCell id="3" value="Evidence" style="rounded=1;whiteSpace=wrap;html=1;" vertex="1" parent="1"><mxGeometry x="280" y="40" width="160" height="60" as="geometry"/></mxCell><mxCell id="4" edge="1" parent="1" source="2" target="3"><mxGeometry relative="1" as="geometry"/></mxCell></root></mxGraphModel></diagram></mxfile>';
export function DrawioExportPanel({
  workflows,
  selectedId,
  onSelected,
  busy,
  onRun,
}: {
  workflows: Workflow[];
  selectedId: string;
  onSelected: (id: string) => void;
  busy: boolean;
  onRun: (action: () => Promise<void>) => Promise<void>;
}) {
  const [source, setSource] = useState(DRAWIO_STARTER_XML),
    [format, setFormat] = useState<"png" | "pdf" | "svg">("png"),
    [result, setResult] = useState<DrawioExportResult>();
  useEffect(() => setResult(undefined), [selectedId]);
  const exportDiagram = () =>
    onRun(async () => {
      if (!selectedId) throw new Error("请先选择工作流");
      const exported = await api<DrawioExportResult>(
        `/api/editor/${selectedId}/drawio-export`,
        { method: "POST", body: JSON.stringify({ source, format }) },
      );
      setResult(exported);
    });
  if (!workflows.length) return null;
  return (
    <Panel
      title="Draw.io 导出"
      detail="使用随安装包提供的 Draw.io CLI 在本地工作区导出 PNG、PDF 或 SVG。每次导出保存 XML 源、运行时哈希、命令结果和清单。"
    >
      <section className="settings-section">
        <div className="form-grid">
          <label>
            工作流
            <select
              aria-label="Draw.io 工作流"
              value={selectedId}
              onChange={(event) => onSelected(event.target.value)}
            >
              {workflows.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.title}
                </option>
              ))}
            </select>
          </label>
          <label>
            导出格式
            <select
              aria-label="Draw.io 导出格式"
              value={format}
              onChange={(event) =>
                setFormat(event.target.value as "png" | "pdf" | "svg")
              }
            >
              <option value="png">PNG</option>
              <option value="pdf">PDF</option>
              <option value="svg">SVG</option>
            </select>
          </label>
        </div>
        <label>
          Draw.io XML
          <textarea
            aria-label="Draw.io XML"
            className="code-editor"
            value={source}
            onChange={(event) => setSource(event.target.value)}
            spellCheck={false}
          />
        </label>
        <div className="actions">
          <button
            disabled={busy || !selectedId || !source.trim()}
            onClick={exportDiagram}
          >
            导出 Draw.io 图
          </button>
          {result && (
            <button
              className="quiet"
              disabled={busy}
              onClick={() =>
                void onRun(() =>
                  download(
                    `/api/editor/${selectedId}/download?path=${encodeURIComponent(result.source.path)}`,
                    "research-diagram.drawio",
                  ),
                )
              }
            >
              下载 XML 源文件
            </button>
          )}
          {result?.outputs[0] && (
            <button
              className="quiet"
              disabled={busy}
              onClick={() =>
                void onRun(() =>
                  download(
                    `/api/editor/${selectedId}/download?path=${encodeURIComponent(result.outputs[0].source.path)}`,
                    `research-diagram.${format}`,
                  ),
                )
              }
            >
              下载导出产物
            </button>
          )}
          {result && (
            <button
              className="quiet"
              disabled={busy}
              onClick={() =>
                void onRun(() =>
                  download(
                    `/api/editor/${selectedId}/download?path=${encodeURIComponent(result.manifest.path)}`,
                    "drawio-export-manifest.json",
                  ),
                )
              }
            >
              下载导出清单
            </button>
          )}
        </div>
        {result && (
          <div
            className={`graph-gate ${result.status === "completed" ? "passed" : "blocked"}`}
          >
            <b>
              {result.status === "completed"
                ? "Draw.io 导出完成"
                : "Draw.io 导出失败"}
            </b>
            <span>
              {result.outputs[0]
                ? `${result.outputs[0].source.path} · SHA256 ${result.outputs[0].source.sha256}`
                : result.failure_reason}
            </span>
            <code>
              {result.manifest.path} · {result.manifest.sha256.slice(0, 16)}
            </code>
          </div>
        )}
        {result?.stderr && <pre className="json-card">{result.stderr}</pre>}
      </section>
    </Panel>
  );
}

type MermaidExportResult = {
  status: string;
  source: { path: string; sha256: string; bytes: number };
  outputs: Array<{
    path?: string;
    source?: { path: string; sha256: string; bytes: number };
    sha256?: string;
    bytes?: number;
    status?: string;
    format?: string;
    width?: number;
    height?: number;
  }>;
  manifest: { path: string; sha256: string };
  failure_reason?: string;
  stderr?: string;
};
const MERMAID_STARTER = `flowchart LR
  Q[Research question] --> E[Evidence card]
  E --> C[Claim]
  C --> A[Assurance gate]
`;
export function MermaidExportPanel({
  workflows,
  selectedId,
  onSelected,
  busy,
  onRun,
}: {
  workflows: Workflow[];
  selectedId: string;
  onSelected: (id: string) => void;
  busy: boolean;
  onRun: (action: () => Promise<void>) => Promise<void>;
}) {
  const [source, setSource] = useState(MERMAID_STARTER),
    [format, setFormat] = useState<"png" | "pdf" | "svg">("svg"),
    [result, setResult] = useState<MermaidExportResult>();
  useEffect(() => setResult(undefined), [selectedId]);
  const exportDiagram = () =>
    onRun(async () => {
      if (!selectedId) throw new Error("请先选择工作流");
      const exported = await api<MermaidExportResult>(
        `/api/editor/${selectedId}/mermaid-export`,
        { method: "POST", body: JSON.stringify({ source, format }) },
      );
      setResult(exported);
    });
  const outputPath = result?.outputs?.[0]
    ? result.outputs[0].path || result.outputs[0].source?.path || ""
    : "";
  const outputSha = result?.outputs?.[0]
    ? result.outputs[0].sha256 || result.outputs[0].source?.sha256 || ""
    : "";
  if (!workflows.length) return null;
  return (
    <Panel
      title="Mermaid 导出"
      detail="使用产品内置 offline mermaid.min.js 与本地 Chromium 浏览器渲染。无网络依赖；每次导出保存源码、HTML、运行时哈希和清单。"
    >
      <section className="settings-section">
        <div className="form-grid">
          <label>
            工作流
            <select
              aria-label="Mermaid 工作流"
              value={selectedId}
              onChange={(event) => onSelected(event.target.value)}
            >
              {workflows.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.title}
                </option>
              ))}
            </select>
          </label>
          <label>
            导出格式
            <select
              aria-label="Mermaid 导出格式"
              value={format}
              onChange={(event) =>
                setFormat(event.target.value as "png" | "pdf" | "svg")
              }
            >
              <option value="svg">SVG</option>
              <option value="png">PNG</option>
              <option value="pdf">PDF</option>
            </select>
          </label>
        </div>
        <label>
          Mermaid 源码
          <textarea
            aria-label="Mermaid 源码"
            className="code-editor"
            value={source}
            onChange={(event) => setSource(event.target.value)}
            spellCheck={false}
          />
        </label>
        <div className="actions">
          <button
            disabled={busy || !selectedId || !source.trim()}
            onClick={exportDiagram}
          >
            导出 Mermaid 图
          </button>
          {result && (
            <button
              className="quiet"
              disabled={busy}
              onClick={() =>
                void onRun(() =>
                  download(
                    `/api/editor/${selectedId}/download?path=${encodeURIComponent(result.source.path)}`,
                    "research-diagram.mmd",
                  ),
                )
              }
            >
              下载 Mermaid 源文件
            </button>
          )}
          {outputPath && (
            <button
              className="quiet"
              disabled={busy}
              onClick={() =>
                void onRun(() =>
                  download(
                    `/api/editor/${selectedId}/download?path=${encodeURIComponent(outputPath)}`,
                    `research-diagram.${format}`,
                  ),
                )
              }
            >
              下载导出产物
            </button>
          )}
          {result && (
            <button
              className="quiet"
              disabled={busy}
              onClick={() =>
                void onRun(() =>
                  download(
                    `/api/editor/${selectedId}/download?path=${encodeURIComponent(result.manifest.path)}`,
                    "mermaid-export-manifest.json",
                  ),
                )
              }
            >
              下载导出清单
            </button>
          )}
        </div>
        {result && (
          <div
            className={`graph-gate ${result.status === "completed" ? "passed" : "blocked"}`}
          >
            <b>
              {result.status === "completed"
                ? "Mermaid 导出完成"
                : "Mermaid 导出失败"}
            </b>
            <span>
              {outputPath
                ? `${outputPath} · SHA256 ${outputSha}`
                : result.failure_reason}
            </span>
            <code>
              {result.manifest.path} · {result.manifest.sha256.slice(0, 16)}
            </code>
          </div>
        )}
        {result?.stderr && <pre className="json-card">{result.stderr}</pre>}
      </section>
    </Panel>
  );
}

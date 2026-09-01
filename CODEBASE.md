# VibeResearch 源码参考文档（供 AI 快速读取）

> 版本：v1.2.2 · 生成时间：2026-07-29
> 此文档由 AI 自动生成，覆盖项目的完整架构与关键模块，便于下次让 AI 快速上手。

---

## 1. 项目定位

**Vibe Research** 是一款面向博士生/科研人员的**本地离线 AI 科研证据工作台**。
- 核心理念：**证据优先、Fail-Closed**——所有主张必须有真实文献或实验数据支撑。
- 交付形式：Electron 桌面应用（Windows/Linux）。
- 源码开发模式：FastAPI 后端 + Vite 前端，无需 Electron 即可在浏览器中运行。

---

## 2. 技术栈一览

| 层次 | 技术 |
|---|---|
| 桌面壳 | Electron 39 (`main.js`, `preload.js`) |
| 后端 | Python FastAPI + Uvicorn · 端口 **18088** |
| 数据库 | SQLite (aiosqlite, WAL 模式) |
| 实时推送 | WebSocket + SSE (Server-Sent Events) |
| 前端 | React 18 + TypeScript + Vite · 开发端口 **5173** |
| 构建打包 | electron-builder · 前端 `dist/` 作为静态资源 |
| Agent | Claude Code CLI / OpenAI Codex CLI / OpenAI-Compatible / Gemini / MiniMax |
| 文档导出 | TeXLive · Pandoc · python-docx · Draw.io |
| 安全 | AES-GCM 加密密钥库；本地会话令牌（`X-Vibe-Session-Token`） |

---

## 3. 顶层目录结构

```
vibe-research/
├── main.js              # Electron 主进程入口
├── preload.js           # Electron 预加载脚本（IPC 桥接）
├── desktop-data.js      # 桌面运行时数据配置
├── updater.js           # 自动更新逻辑
├── package.json         # Electron + electron-builder 配置
├── start.bat            # 源码开发模式一键启动脚本（Windows）
├── run.py               # 可选 Python 启动入口
│
├── backend/             # Python FastAPI 后端（见第4节）
├── frontend/            # React TypeScript Vite 前端（见第5节）
├── skills/              # 150+ AI 技能包（SKILL.md 驱动）
├── templates/           # LaTeX/DOCX 文档模板
├── tools/               # 工具脚本（scholar · reviewer · docx · tikz 等）
├── runtime/             # 离线运行时（Python · Node · TeXLive · Pandoc）
├── dist/                # 前端构建产物（npm run build 生成）
├── tests/               # 端对端测试 / 后端测试
├── scripts/             # 构建与发布脚本（PowerShell）
└── docs/                # 项目截图与文档
```

---

## 4. 后端架构（`backend/`）

### 4.1 入口与配置

| 文件 | 说明 |
|---|---|
| `main.py` | FastAPI `app` 实例；注册所有 Router；`lifespan` 负责数据库初始化、工作流恢复、心跳 |
| `config.py` | 运行时布局解析；区分**桌面模式**（`IS_DESKTOP=True`）和**源码模式**；路径常量：`DB_PATH`, `SKILLS_DIR`, `WORKSPACES_DIR`, `RUNTIME_PYTHON` 等 |

**运行模式判断逻辑（`config.py`）：**
- 环境变量 `VIBE_DESKTOP=1` → 桌面模式
- 存在 `runtime/` 目录 → 桌面模式
- 否则 → 源码开发模式（`IS_DESKTOP=False`，前端用 Vite 代理）

**关键环境变量：**
```
API_PORT=18088          # 后端端口（默认 18088）
VIBE_DESKTOP=1          # 强制桌面模式
VIBE_RUNTIME_ROOT=...   # 自定义运行时目录
VIBE_USER_DATA_ROOT=... # 自定义用户数据目录
```

### 4.2 Router 层（`backend/routers/`）

每个 Router 对应一组 REST API：

| Router | 前缀/说明 |
|---|---|
| `research.py` | `/api/research-projects` — 项目 CRUD、假设、证据卡片、筛选、稿件 |
| `research_runs.py` | `/api/research-runs` — 研究运行（Golden Path 步骤机）|
| `workflows.py` | `/api/workflows` — 工作流 CRUD、步骤控制、断点续跑、SSE 事件流 |
| `literature.py` | `/api/literature` — 文献检索（AMiner/Semantic Scholar/CrossRef/DBLP）|
| `agents.py` | `/api/agents` — Agent 任务（Claude/Codex/OpenAI）、协作任务 |
| `artifacts.py` | `/api/workflows/{id}/artifacts` — 工件管理（上传/下载）|
| `checkpoints.py` | `/api/workflows/{id}/checkpoints` — 人工审批断点 |
| `settings.py` | `/api/settings/model-profiles` — AI 模型配置、测试 |
| `editor.py` | `/api/editor` — AI 辅助编辑 |
| `experiments.py` | `/api/experiments` — 实验设计与执行 |
| `narrative.py` | `/api/research-projects/{id}/narrative` — 科学叙事地图 |
| `drafts.py` | `/api/research-projects/{id}/draft` — 草稿生成与保存 |
| `docx_export.py` | DOCX 导出 |
| `project_preview.py` | 项目预览服务器管理 |
| `environment.py` | `/api/environment` — 运行环境检测 |
| `ws.py` | WebSocket 实时日志推送 |

### 4.3 Service 层（`backend/services/`）

核心业务逻辑：

| 服务 | 说明 |
|---|---|
| `workflow_engine.py` | 工作流编排引擎；34 个模板；步骤状态机；`run_workflow()` 异步任务 |
| `workflow_operations.py` | 运营视图：多工作流聚合、SSE 事件发布 |
| `agent_tasks.py` | Agent 任务调度与生命周期（启动/取消/重试/恢复）|
| `agent_adapters.py` | 适配器工厂：Claude CLI · Codex CLI · OpenAI Compatible · Gemini · MiniMax |
| `claude_runner.py` | Claude Code CLI 执行器 |
| `llm_client.py` | 通用 LLM HTTP 客户端（OpenAI-Compatible 协议）|
| `state_store.py` | SQLite 状态持久化；工作流日志、checkpoint、工件 |
| `secret_store.py` | AES-GCM 加密密钥存储 |
| `research_contracts.py` | 研究合同服务 |
| `evidence_screening.py` | PRISMA 协议筛选 |
| `scientific_narrative.py` | 科学叙事地图逻辑 |
| `adversarial_review.py` | 对抗性审稿（确定性 + 模型双模式）|
| `innovation_check.py` | 创新性检查（新颖度评估）|
| `manuscript_projection.py` | 从已审批事实派生草稿 |
| `project_server.py` | 每个项目的预览服务器管理 |
| `skill_registry.py` | Skills 加载与注册 |
| `model_profiles.py` | 模型配置管理（executor/reviewer/editor_ai）|
| `local_session.py` | 桌面模式本地会话令牌验证 |

### 4.4 Domain 层（`backend/domain/`）

纯业务实体，无 I/O：

| 模块 | 说明 |
|---|---|
| `entities.py` | 核心实体：`Project`, `EvidenceCard`, `HypothesisVersion`, `ResearchRun` 等 |
| `research_run.py` | Golden Path 步骤状态机（研究运行）|
| `serialization.py` | 序列化/反序列化工具 |
| `assurance/` | 证据质量门控（数值注册表、统计门控、论文数字核验）|
| `evidence/` | 证据卡片、来源管理 |
| `experiments/` | 实验规划与隔离执行 |
| `narrative/` | 科学叙事地图、主张图、提交质量 |

### 4.5 Infrastructure 层（`backend/infrastructure/`）

| 模块 | 说明 |
|---|---|
| `persistence/` | SQLite Repository 实现（研究项目、研究运行、语义导出、迁移）|
| `literature/` | 文献数据源：AMiner · Semantic Scholar · CrossRef · DBLP；引文核验；PDF 导入 |
| `execution/` | 工作流执行 manifest 存储 |

### 4.6 数据库（SQLite）

- **位置（源码模式）：** `runtime/backend/vibe.db`
- **位置（桌面模式）：** `%APPDATA%\VibeResearch\db\vibe.db`
- 模式定义：`backend/db/schema.sql`
- 使用 aiosqlite WAL 模式，支持并发读写
- 迁移由 `infrastructure/persistence/migrations.py` 在启动时自动执行

---

## 5. 前端架构（`frontend/`）

### 5.1 技术配置

| 文件 | 说明 |
|---|---|
| `package.json` | 依赖：React 18 · TypeScript · Vite（latest） |
| `vite.config.ts` | 开发代理：`/api/*` → `http://127.0.0.1:18088`；构建输出 `../dist/` |
| `src/styles.css` | 全局样式 |

**开发模式数据流：**  
浏览器 `:5173` → Vite 代理 → FastAPI `:18088`  
前端调用 `/api/...` 时 Vite 自动转发，无需 CORS 配置。

### 5.2 页面/组件（`frontend/src/`）

| 文件 | 说明 |
|---|---|
| `main.tsx` | React 根组件；路由、状态管理、所有页面的入口（**单文件 SPA**，全部 UI 均在此）|
| `cockpit.tsx` | 工作台看板组件（研究进度、证据覆盖率、工作流状态概览）|
| `evidence-page.tsx` | 证据库页（文献检索、证据卡片审批、PRISMA 筛选）|
| `research-map.tsx` | 研究地图页（科学叙事地图、主张-证据图）|
| `workflow-operations.tsx` | 工作流运营面板（多工作流 SSE 实时流、重试/恢复操作）|
| `workflow-config.tsx` | 工作流配置与启动表单 |
| `api.ts` | **所有 API 类型定义 + 所有 API 调用函数**（集中管理）|
| `ui.tsx` | 通用 UI 组件（按钮、对话框、表单等）|
| `feature-routes.ts` | 功能路由逻辑 |
| `route-boundary.ts` | 路由边界守卫 |
| `research-helpers.ts` | 研究相关工具函数 |
| `status.ts` | 状态枚举与工具 |
| `generated/openapi.ts` | 从 OpenAPI schema 生成的类型 |

> **注意**：`main.tsx` 是核心 SPA 文件，所有页面路由和主要逻辑都在此。该文件超过 256KB，需分段阅读。

### 5.3 关键 API 类型（`frontend/src/api.ts`）

前端定义的核心 TypeScript 类型（与后端 Pydantic 模型对应）：

| 类型 | 说明 |
|---|---|
| `Project` | 研究项目（含 artifacts, evidence_cards, hypotheses）|
| `EvidenceCard` | 证据卡片（含 citation_status, claim_support_status）|
| `HypothesisVersion` | 假设版本（draft/frozen/falsified/superseded）|
| `Workflow` | 工作流（含 steps, status, params）|
| `WorkflowLog` | 工作流日志条目 |
| `WorkflowCheckpoint` | 人工审批断点 |
| `WorkflowOperationsRun` | 运营视图的工作流概要 |
| `ResearchRun` | Golden Path 研究运行（步骤状态机）|
| `ExperimentRun` | 实验运行（含统计门控结果）|
| `AgentTask` | Agent 任务（Claude/Codex/OpenAI）|
| `NarrativeMap` | 科学叙事地图 |
| `ClaimEvidenceGraph` | 主张-证据图 |
| `ModelProfile` | AI 模型配置（executor/reviewer/editor_ai）|
| `AssuranceEnvelope` | 质量保证信封（PASS/WARN/BLOCKED）|

**API 调用约定：**
- 所有请求经 `api<T>(path, options)` 包装
- 自动附加 `X-Vibe-Session-Token` 请求头（桌面模式鉴权）
- SSE 流通过 `streamWorkflowOperationsEvents()` 消费

---

## 6. Skills 系统（`skills/`）

Skills 是 AI 技能包，每个技能由 `SKILL.md` 文件驱动。后端 `skill_registry.py` 负责加载。

部分技能目录示例：
```
skills/
├── ablation-planner/     # 消融实验规划
├── analyze-results/      # 结果分析
├── arxiv/                # arXiv 检索
├── auto-review-loop/     # 自动审稿循环
├── comp-modeling/        # 竞赛建模
├── comp-paper-en/        # 竞赛论文（英文）
├── auto-paper-improvement-loop/  # 论文自动改进循环
└── ...（共 150+ 技能）
```

工作流模板在 `workflow_engine.py` 中注册，每个模板由多个 Skill 步骤组成。

---

## 7. Electron 层（桌面模式）

| 文件 | 说明 |
|---|---|
| `main.js` | Electron 主进程：创建 BrowserWindow、系统托盘、自动更新、IPC 处理、启动 Python 后端 |
| `preload.js` | 预加载脚本：暴露 `window.electronAPI`（`localSessionToken`, `selectDataDirectory`）|
| `desktop-data.js` | 桌面运行时数据（版本、路径等）|
| `updater.js` | 基于 electron-updater 的自动更新 |

**桌面模式下的安全机制：**  
Electron 主进程生成一次性 `local-session-token`，通过 IPC 传给前端，前端每次请求携带此令牌。后端 `local_session.py` 验证令牌，防止局域网内其他进程访问 API。

---

## 8. 配置与密钥（`.env` / 设置页）

`.env.example` 列出的环境变量（放项目根目录的 `.env`）：

```env
AMINER_API_KEY=           # AMiner 学术数据库 API Key
AMINER_BASE_URL=https://datacenter.aminer.cn
GPT_IMAGE_API_KEY=        # 图像生成 API Key
GPT_IMAGE_BASE_URL=
OPENAI_API_KEY=           # OpenAI / 兼容 API Key
OPENAI_BASE_URL=          # 自定义 API 地址
REVIEWER_MODEL_ID=        # 审稿 Agent 模型 ID
```

密钥也可通过应用内 **设置 → 模型配置** 页面配置，使用 AES-GCM 加密存于本地。

---

## 9. 研究工作流（Golden Path）

`backend/application/golden_path.py` 定义了研究步骤顺序：

```
research_contract  →  literature_search  →  evidence_screening
→  hypothesis_registry  →  narrative_map  →  experiment_planning
→  experiment_execution  →  claim_evidence_graph  →  manuscript_projection
→  adversarial_review  →  paper_export
```

每步均有 checkpoint，支持中断后从断点恢复（`ResearchRun` 状态机）。

---

## 10. 开发模式启动（源码模式）

> **⚠️ 启动纪律（2026-09-01 确立）：后端一律由人工启动，禁止 AI 助手代劳。**
>
> 原因：AI 助手（WorkBuddy 等）通过工具调用派生的进程树会被宿主的 **safe-delete 沙箱钩子**注入，
> 该钩子拦截文件删除并要求回收站通道——后端进程上下文无法提供，删除被 fail-closed 拦截
> （`SAFE_DELETE_FAIL_CLOSED`）。后果：`skill_crypto._retry_rmtree` 清理 `_utils/` 永远失败，
> 只能靠 rename-aside 让位，工作区堆积 `_utils.stale-*` 残留（真实案例：fb4f4e5b7272 堆了 17 个）；
> 批量删除守卫还可能误伤 `.git`（2026-09-01 发生过 refs/pack 被删、9 个本地提交对象丢失的事故）。
>
> 规则：
> - **后端启动/重启**：由用户在自有终端执行 `start.bat`（或桌面 Electron 应用，其由 main.js 直接
>   spawn Python，天然不在沙箱内）。
> - **AI 助手需要后端重启时**：明确告知用户"请重启后端"，不要自己 spawn 后端进程。
> - AI 派生的**短命只读进程**（查询、测试、curl）不受此限；涉及删除/长驻留的一律人工。
>
> 验证后端是否在沙箱外：删除通道正常时，步骤重挂载不会再产生新的 `_utils.stale-*` 目录。

### 前提条件
- Python 3.x 已安装（`pip install -r backend/requirements.txt`）
- Node.js 已安装（`cd frontend && npm install`）

### 启动方式（人工执行）
```bash
# 终端1：启动后端（热重载）
cd backend
python -m uvicorn main:app --reload --port 18088

# 终端2：启动前端 Vite 开发服务器
cd frontend
npm run dev
```

注：`--reload` 在 Windows 下会使 uvicorn 选用 SelectorEventLoop（不支持 asyncio 子进程），
`_run_process` 已内置同步兜底（见 §12.8 顶部修正块），无需为此去掉热重载。

浏览器访问：**http://localhost:5173**

### 数据存储位置（源码模式）
- 数据库：`runtime/backend/vibe.db`
- 工作区：`runtime/workspaces/`
- **后端日志**：`runtime/backend/logs/backend.log`（轮转，5 × 10MB；桌面模式在 `%APPDATA%\VibeResearch\db\logs\backend.log`）

### 后端日志（诊断必读）

`backend/main.py` 启动时通过 `RotatingFileHandler` 把 root logger 同时写到 stderr 和文件：

- **源码模式**：`runtime/backend/logs/backend.log`（含 `.1`~`.5` 轮转历史）
- **桌面模式**：`%APPDATA%\VibeResearch\db\logs\backend.log`

uvicorn 的 logger 默认传播到 root logger，因此 HTTP 访问日志、异常 traceback、`log.error("Step execution failed: ...")` 等全部落盘。**排查工作流静默失败时第一件事就是读这个文件的最后 200 行**，不要依赖弹出的 cmd 控制台窗口（自动化无法读取其缓冲区）：

```bash
tail -n 200 runtime/backend/logs/backend.log
```

数据库辅助排查（步骤/尝试/恢复操作状态）：

```bash
python -c "import sqlite3; c=sqlite3.connect('runtime/backend/vibe.db'); c.row_factory=sqlite3.Row; \
print([dict(r) for r in c.execute('SELECT skill_name,status,error_message FROM workflow_steps WHERE workflow_id=?', ('<wf_id>',))])"
```

### 构建生产版本
```bash
cd frontend && npm run build   # 输出到 ../dist/
npm run build:release          # 打包 Windows 安装包
```

---

## 11. 关键文件速查

| 需要了解的功能 | 找哪个文件 |
|---|---|
| API 端口 / 路由入口 | `backend/main.py` |
| 运行模式 / 路径配置 | `backend/config.py` |
| 工作流模板定义 | `backend/services/workflow_engine.py` |
| Agent 执行逻辑 | `backend/services/agent_adapters.py`, `claude_runner.py` |
| 前端所有 API 调用 | `frontend/src/api.ts` |
| 前端主 SPA 组件 | `frontend/src/main.tsx` |
| Vite 代理配置 | `frontend/vite.config.ts` |
| 数据库 schema | `backend/db/schema.sql` |
| 密钥存储 | `backend/services/secret_store.py` |
| Electron 主进程 | `main.js` |
| 会话令牌验证 | `backend/services/local_session.py` |

---

## 12. 工作流步骤 rc=1 故障诊断手册

> 适用场景：某 workflow 步骤反复以 `rc=1` 失败并触发 auto-retry（日志显示 `auto-retry attempt N/8`），  
> 而非业务逻辑返回失败（例如 AI 报告内容不合格）。

---

### 12.1 rc=1 的两种含义

| 来源 | 含义 | 如何区分 |
|---|---|---|
| **工具调用被 sandbox 拒绝** | `run_command` 抛出 `ValueError`，agent 的工具返回 `{"ok":false,"error":"..."}` | 日志含 `command not allowlisted` / `not allowlisted` / `WorkspaceBoundaryError` |
| **业务校验失败** | `check_*.py` 等脚本发现内容错误，正常退出码 1 | 日志含 `ERROR:` 前缀的校验输出行，无 allowlist 字样 |
| **OS 层面进程创建失败** | `asyncio.create_subprocess_exec` 抛出底层异常，工具返回 `{"ok":false,"error":"NotImplementedError: "}` | 日志含 `NotImplementedError: `（消息为空），且 `python --version` 等最基础命令也同样失败 |

**首先区分这三类**。本手册主要针对第一类（sandbox 拒绝）和第三类（OS 级别失败，见 12.8）。

---

### 12.2 Sandbox 限制速查（`WorkspaceTools`）

核心类：`backend/services/openai_responses_agent.py` → `WorkspaceTools`

#### 允许的命令（`_ALLOWED_COMMANDS`，约第 33 行）
```python
{"python", "python3", "node", "npm", "npx", "pdflatex", "xelatex",
 "bibtex", "biber", "pandoc", "git", "pytest", "ruff", "mypy", "bash"}
```
**不在此集合内的命令一律报 `command not allowlisted: <name>`。**

#### python/python3 额外限制（约第 491 行）
```python
if executable_name in {"python", "python3"} and any(
    item in {"-m", "-", "-c"} for item in argv[1:]
):
    raise ValueError("interpreter inline and module execution are not allowlisted")
```
- **`-c`**（内联代码）、**`-m`**（模块）、**`-`**（stdin）均被禁止。
- 只能用 `python3 <script.py> [args]` 形式运行 Python。

#### bash 限制（约第 495 行）
- `bash` 在 `_ALLOWED_COMMANDS` 中，允许 `bash -c "..."` 形式。
- 其他命令若通过 bash 子进程调用（如 `grep`、`awk`），不受 allowlist 约束——bash 是 argv[0]，grep 是 bash 内部调用。

#### Workspace 边界
- 任何读写操作若路径解析到 workspace 根目录之外 → `WorkspaceBoundaryError`。
- workspace 根 = 该步骤对应的运行时目录（如 `runtime/workspaces/<id>/`）。

---

### 12.3 SKILL.md 中的常见陷阱

以下写法会导致 agent 调用失败（历史上已踩过的坑）：

| 写法 | 错误原因 | 正确替代 |
|---|---|---|
| `` ```bash\nwc -c < file\n``` `` | `wc` 不在 allowlist | 用 `python3 _utils/check_*.py` |
| `python3 - <<'PY'\n...\nPY` | stdin 模式 `-` 被禁止 | 把脚本存为 `.py` 文件，用 `python3 script.py` 调用 |
| `python3 -c "import re; ..."` | `-c` 被禁止 | 同上，存为脚本文件 |
| `cmd 2>&1 \| tee out.txt` | pipe 是 shell 语法，`run_command` 不经 shell 解释 | 分两步：先 `run_command` 捕获输出，再 `write` 写文件 |
| `grep -c / grep -q` 作为顶层命令 | `grep` 不在 allowlist | 用 `python3 -` 脚本（存文件）或 `bash -c "grep ..."` |
| 路径写 `.vibe-skills/<skill>/references/xxx.md` | 若文件实际在 `_utils/`，路径不符导致 `WorkspaceBoundaryError` | 核对挂载映射（见 12.4） |

---

### 12.4 workspace 目录挂载映射

运行时 workspace 内的目录名 ↔ 源码目录：

| workspace 内路径 | 源码目录 |
|---|---|
| `_utils/` | `skills/shared-scripts/` |
| `.vibe-skills/<skill-name>/` | `skills/<skill-name>/` |
| `PROBLEM_ANALYSIS.md` 等工件 | 上一步骤产出，位于 workspace 根 |

**因此：**  
- 跨 skill 的共享脚本放 `skills/shared-scripts/`，在 SKILL.md 里引用为 `_utils/<script>.py`。  
- Skill 自身的私有文件（如 `methods_table.md`）在 SKILL.md 里引用为 `.vibe-skills/<skill-name>/references/<file>`，这是合法路径。

---

### 12.5 诊断步骤（遇到 rc=1 时的操作顺序）

```
1. 打开该步骤的完整日志（WorkspaceTools 日志 / SSE 事件流）
   └─ 搜索关键词：allowlisted | WorkspaceBoundaryError | ERROR | rc=1

2. 如果含 "not allowlisted"
   ├─ 找出被拒绝的命令名（错误信息里的 <name>）
   ├─ 在对应 SKILL.md 里全文搜索该命令
   └─ 按 12.3 的映射表替换为合规写法

3. 如果含 "WorkspaceBoundaryError"
   ├─ 找出违规路径
   ├─ 对照 12.4 的挂载映射，核对路径是否写错
   └─ 修正为正确的 workspace 内相对路径

4. 如果含 "interpreter inline and module execution are not allowlisted"
   ├─ SKILL.md 里有 python3 -c / python3 -m / python3 - <<'PY' 写法
   └─ 提取 heredoc/inline 代码，另存为 skills/shared-scripts/<name>.py，
      在 SKILL.md 里改用 python3 _utils/<name>.py

4b. 如果含 "NotImplementedError: "（错误消息为空字符串）
   ├─ 特征：python --version、python3 script.py 等最基础命令全部失败
   ├─ 原因：Windows PATH 中 Microsoft Store 的 python.exe stub（app execution alias）
   │        排在真实 Python 之前；该 stub 在 CREATE_NO_WINDOW 模式下无法被
   │        asyncio.create_subprocess_exec 启动，ProactorEventLoop 报 NotImplementedError
   ├─ 立即修（无需重启后端）：
   │        Windows 设置 → 应用 → 高级应用设置 → 应用执行别名
   │        → 关闭 python.exe 和 python3.exe 的开关
   │        关闭后 WindowsApps 目录中的 stub 文件被删除，subprocess 自动回落到
   │        PATH 后续条目中的真实 Python（如 AppData\Local\Python\bin\python.exe）
   └─ 代码修（重启后端后永久生效）：
            openai_responses_agent.py 的 _run_command 方法已在构建 subprocess
            环境变量时过滤掉 PATH 中所有含 "WindowsApps" 的条目（见 12.8）

5. 如果日志只有业务 ERROR（check 脚本输出）而无 allowlist 字样
   └─ 这是正常的内容质量门控，不是 sandbox 问题，应修复报告内容

6. 修改 SKILL.md 后，若 backend 代码也有变动，**请用户人工重启 FastAPI**（端口 18088）——见 §10 启动纪律
```

---

### 12.6 已知根因修复记录（2026-07-30）

针对 `comp-modeling` / `comp-code` workflow 的 `rc=1` 循环，本次修复了以下问题：

| 文件 | 修复内容 |
|---|---|
| `skills/comp-modeling/SKILL.md` | 4处 `error_prevention.md` 路径错误（`.vibe-skills/...` → `_utils/`）|
| `skills/comp-modeling/SKILL.md` | PASS gate `wc -c` bash块 → `python3 _utils/check_modeling.py` |
| `skills/comp-modeling/SKILL.md` | 大bash自检块（grep -c/q 等）→ `python3 _utils/check_modeling.py` |
| `skills/comp-modeling/SKILL.md` | `facts_audit 2>&1 \| tee` pipe → 分步显式写入 |
| `skills/comp-modeling/SKILL.md` | LaTeX扫描 `python3 - <<'PY'` heredoc → `python3 _utils/check_latex.py` |
| `skills/shared-scripts/check_modeling.py` | 新增：替代全部bash校验逻辑的Python脚本 |
| `skills/shared-scripts/check_latex.py` | 新增：替代heredoc的LaTeX裸命令扫描脚本 |
| `backend/services/openai_responses_agent.py` | `-c` 加入python屏蔽集；错误消息与测试用例对齐 |
| `backend/services/openai_responses_agent.py` | `_run_command` 中在构建子进程环境时过滤 PATH 里的 `WindowsApps` 条目，防止 Store python.exe stub 引发 `NotImplementedError`（见 12.8）|
| `backend/services/openai_responses_agent.py` | `use_shell=True` 分支中 `argv[0]` 由 `shutil.which` 绝对路径改为裸名，防止安全检查自我误杀（见 12.9）|

---

### 12.8 Windows App Execution Alias 引发的 NotImplementedError

> **⚠️ 2026-09-01 归因修正（fb4f4e5b7272 复核定案）**：裸 `NotImplementedError`（空消息）有**两个**充分条件，排查时先看 traceback 栈帧落点：
>
> | 栈帧落点 | 根因 | 处置 |
> |---|---|---|
> | `asyncio/base_events.py` 的 `_make_subprocess_transport`（基类 `raise NotImplementedError`） | **当前事件循环是 SelectorEventLoop**（Windows 上根本不支持子进程）。最常见诱因：`uvicorn --reload` 或 `--workers>1` —— uvicorn ≥0.36 的 `loop_factory` 在 win32+`use_subprocess` 时强制 SelectorEventLoop，且**完全绕过** `asyncio.set_event_loop_policy()`（`main.py` 里的 Proactor 策略对 uvicorn 是死代码） | 去掉 `--reload`；或依赖 `_run_process` 的第三层同步兜底（已修复，见下） |
> | `windows_events.py` / `proactor_events.py` 内部 | 才是本节的 App Execution Alias / IOCP 问题 | 按本节下文处理 |
>
> **判断口诀**：去掉 creationflags 重试后**仍失败** ≈ 循环类型问题；重试后成功 ≈ alias/flags 问题。
>
> **已修复（2026-09-01）**：`workflow_engine._run_process` 现在有第三层兜底——两次 asyncio 尝试均失败后改用 `asyncio.to_thread(subprocess.run)`（与 `openai_responses_agent._run_command_sync_fallback` 同款），SelectorEventLoop 下 probe/host-fallback/导出类 host 步骤均可工作。回归测试：`tests/test_host_run_process_fallback.py`。

#### 症状
所有 `run_command` 工具调用——包括 `python --version` 这类最基础的命令——均返回：
```json
{"ok": false, "error": "NotImplementedError: "}
```
（注意错误消息为**空字符串**，区别于 `ValueError: command not allowlisted`）

#### 根因
Windows 在 `%APPDATA%\Local\Microsoft\WindowsApps\` 目录中放置了 Microsoft Store 的
Python **app execution alias**（零字节 reparse point 文件 `python.exe` / `python3.exe`）。  
该目录通常排在系统 PATH 的前列，真实 Python（如 `AppData\Local\Python\bin\`）排在其后。

`_run_command` 使用 `asyncio.create_subprocess_exec` + `CREATE_NO_WINDOW` 标志创建子进程。
在无窗口的非交互上下文中，Store stub 的 reparse point 重定向机制无法触发，
`ProactorEventLoop` 内部的 Windows IOCP 调用返回错误，Python 将其暴露为 `NotImplementedError`（无消息）。

#### 验证方法
```
where python
```
若第一行为 `...\WindowsApps\python.exe` → 即为此问题。

#### 修复（二选一，或两者均做）

**A. 系统级修复（立即生效，无需重启后端）**

> Windows 设置 → 应用 → 高级应用设置 → 应用执行别名  
> 将 **python.exe** 和 **python3.exe** 的开关关闭。

关闭后 `WindowsApps\python.exe` 文件被移除，`CreateProcess` 解析 `python` 时自动跳至
PATH 后续条目中的真实可执行文件。

**B. 代码级修复（重启后端后永久生效）**

`backend/services/openai_responses_agent.py` → `WorkspaceTools._run_command`，
在构建 subprocess 环境变量字典之后、调用 `asyncio.create_subprocess_exec` 之前：

```python
if os.name == "nt":
    _clean_path = os.pathsep.join(
        p for p in env.get("PATH", "").split(os.pathsep)
        if "WindowsApps" not in p
    )
    if _clean_path:
        env["PATH"] = _clean_path
```

此段代码已于 2026-07-30 写入（约第 452 行）。重启 FastAPI 后对所有后续 workflow 均生效。

---

### 12.9 `shell=true` + `shutil.which` 绝对路径触发安全检查自我误杀

#### 症状
agent 调用 `run_command` 时设置 `"shell": true`（如环境检查或多命令 bash 脚本），返回：
```json
{"ok": false, "error": "ValueError: command path must be a bare allowlisted program name"}
```
命令本身是 `bash`（在白名单内），但仍报此错误。

#### 根因
`_run_command` 的 `use_shell=True` 分支（Windows 路径）调用 `shutil.which("bash")` 确认
bash 是否存在，然后**将其返回的绝对路径直接用作 `argv[0]`**：

```python
# 有问题的原始代码
bash = shutil.which("bash", path=env.get("PATH"))
if bash:
    argv = [bash, "--noprofile", "--norc", "-lc", shell_text]
    #        ^^^^ 例如 "C:\Program Files\Git\usr\bin\bash.exe"
```

随后第 494 行的安全检查：
```python
if Path(raw_executable).is_absolute() or "/" in raw_executable or "\\" in raw_executable:
    raise ValueError("command path must be a bare allowlisted program name")
```
绝对路径中含有 `\\`，触发异常——sandbox 的安全检查把自己逻辑误杀。

#### 修复（2026-07-30，已写入）
`shutil.which` 仅用于存在性探测，`argv[0]` 改为裸名，由 `create_subprocess_exec` 通过
过滤后的 `env["PATH"]` 自行解析：

```python
if bash:
    # Use bare name so the absolute-path security check passes.
    argv = ["bash", "--noprofile", "--norc", "-lc", shell_text]
elif powershell:
    _ps_name = "pwsh" if shutil.which("pwsh", path=env.get("PATH")) else "powershell"
    argv = [_ps_name, "-NoProfile", "-NonInteractive", "-Command", shell_text]
```

**重启后端后生效。** 配合 12.8 的 WindowsApps PATH 过滤，重启后两个问题均消除。

---

### 12.7 添加新命令到 allowlist

若确实需要某命令（如 `jq`、`ffmpeg`），在 `backend/services/openai_responses_agent.py` 约第 33 行修改：

```python
_ALLOWED_COMMANDS = {
    "python", "python3", "node", "npm", "npx",
    "pdflatex", "xelatex", "bibtex", "biber",
    "pandoc", "git", "pytest", "ruff", "mypy", "bash",
    # 在此追加
    "jq",
}
```

修改后需重启后端。**不要在 SKILL.md 里写未在此集合中的命令名作为顶层调用。**

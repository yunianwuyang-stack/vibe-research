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

### 前提条件
- Python 3.x 已安装（`pip install -r backend/requirements.txt`）
- Node.js 已安装（`cd frontend && npm install`）

### 启动方式
```bash
# 终端1：启动后端（热重载）
cd backend
python -m uvicorn main:app --reload --port 18088

# 终端2：启动前端 Vite 开发服务器
cd frontend
npm run dev
```

浏览器访问：**http://localhost:5173**

### 数据存储位置（源码模式）
- 数据库：`runtime/backend/vibe.db`
- 工作区：`runtime/workspaces/`

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


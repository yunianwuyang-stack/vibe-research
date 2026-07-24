# Vibe-research 源码深度审计报告

- 审计日期：2026-07-11
- 审计对象：`D:\科研软件制作\Vibe-research源码`
- 审计方式：静态代码审阅、目录/依赖盘点、后端导入与路由验证、现有测试运行、关键 API 冒烟、科研工作流与写作规则审阅
- 说明：本报告不修改源码；“顶刊能力”理解为提升研究质量、证据可信度、可复现性与学术表达能力，不代表软件可以保证录用。

## 一、执行摘要

当前项目不是空壳。它已经形成了一个 **Electron 桌面壳 + FastAPI 本地后端 + SQLite 状态机 + Claude Code CLI 执行器 + Markdown 技能库 + LaTeX/DOCX/绘图工具链** 的科研自动化原型，并拥有断点续跑、工作流模板、检查点、日志/WebSocket、文件导入导出、论文/竞赛/开题/综述等多类流程。技能库中也已经存在较好的雏形：文献真实性提示、Claims–Evidence Matrix、实验诚信规则、外部审稿、去 AI 腔、图表规范以及 Nature 风格写作规则。

但它目前仍不适合直接作为“博士生日常生产工具”发布，更不能据此宣称具备稳定的顶刊生成能力。核心原因不是模型不够强，而是 **控制平面、证据平面和产品平面没有真正闭环**：

1. 多个前端已调用的编辑器 API 在服务层根本不存在，真实点击会返回 500；另有若干 Agent API 只是成功占位符。
2. 开发态路径解析错误，源码目录下的 `runtime` 会被解析成 `D:\runtime`；开发运行时可能找不到内置 Python、Claude、Pandoc、Draw.io。
3. 大量技能依赖 `_utils`、`$REVIEWER_SCRIPT`、`$SCHOLAR_SCRIPT`，但引擎没有统一把共享工具复制/挂载到工作区，也没有把两个脚本变量注入子进程环境。关键审稿和文献核查存在静默降级风险。
4. `full_pipeline` 直接从实验生成进入写作，没有把 `experiment-audit`、`result-to-claim`、`paper-claim-audit`、`citation-audit`、`proof-checker` 作为机器强制门禁。仓库虽包含部分审计技能和 assurance 文档，但主流程未接线，且 `verify_paper_audits.sh` 不存在。
5. 设置 API 会原样返回全部 API Key，SQLite 也明文保存；后端无认证、CORS 全开放，同时提供任意脚本执行和无权限限制的 Claude CLI。
6. 测试更偏“恢复已安装 ABI/模板矩阵”，缺少真正科研质量、API 合同、安全边界和端到端验收。实测 28 个后端测试中 27 通过、1 失败；pytest 安装损坏；打包 Electron 验收因 exe 缺失失败。
7. 写作规则已经意识到“工程味/AI 味”，但常规写作流程仍以文件大小、页数下限和审稿模型 6/10 为主要阈值，容易诱导注水和“审稿分数优化”，而不是科学问题、机制、证据与边界的优化。

**结论：** 当前成熟度约为“功能丰富的内部科研 Agent 原型 / alpha”，不是“可靠科研工作站”。最优策略不是继续堆仓库、堆 prompt，而是先用 6–10 周把 P0/P1 基础闭环做实，再扩展多智能体和领域插件。

---

## 二、技术栈与目录结构

### 2.1 技术栈

| 层 | 当前实现 | 评价 |
|---|---|---|
| 桌面端 | Electron 主进程 `main.js`、`preload.js` | 已有托盘、后端启动、端口探测、运行时检查；缺正式 npm 构建配置与安全策略收口 |
| 前端 | 仅保留 Vite/React 打包产物 `dist/assets/index-*.js` | 可运行但不可维护；仓库内没有前端源码、类型检查、组件测试、源码映射 |
| 后端 | FastAPI + Uvicorn | API 面较全，但接口实现与服务层不一致 |
| 持久化 | SQLite + aiosqlite，WAL | 适合本地单用户；schema 与迁移机制过弱 |
| 工作流 | `backend/services/workflow_engine.py`，硬编码模板/状态机 | 能用，但 2490 行单体、科研门禁未结构化 |
| Agent 执行 | Claude Code CLI 非交互执行 | 具备工具调用能力；权限边界过大，变量/工具注入不完整 |
| LLM | OpenAI-compatible HTTP + reviewer/editor/executor 三角色 | 有角色分离概念，但 reviewer 可静默缺席，设置密钥泄露 |
| 文献 | AMiner / Semantic Scholar / CrossRef / DBLP 工具 | 有真实性意识；缺系统综述协议、撤稿检查、检索快照与证据级全文定位 |
| 文档 | LaTeX、XeLaTeX/MiKTeX、Pandoc、python-docx、Node DOCX | 工具丰富，但 DOCX/编辑器合同存在断裂 |
| 科研技能 | 156 个 `SKILL.md`（含嵌套 skill pack） | 内容丰富但重复、漂移、未版本化/未做依赖解析 |
| 运行时 | Python、Node/Claude、Git、Draw.io、Pandoc；约 5.2 GB | 离线能力强，但体积巨大、版本不可复现、pytest 安装残缺 |

### 2.2 目录概览

- `backend/`：FastAPI、路由、SQLite、工作流引擎、LLM/Claude runner。
- `dist/`：编译后的前端；缺少源代码目录。
- `runtime/`：约 5.2 GB 的便携运行时。
- `skills/`：顶层 84 个目录，递归共 156 个 `SKILL.md`；另有 `skills-codex`、`skills-codex-claude-review`。
- `skills_encrypted_backup/`：约 165 MB 的加密备份；但 `skills/.skill_meta.json` 同样宣称 encrypted，实际 plaintext。
- `templates/`：Research Contract、Experiment Plan、Findings、Paper Plan 等模板。
- `tools/`：文献、审稿、图像、DOCX、绘图检查等工具；部分关键工具仅以 `.pyc` 分发。
- `tests/`：后端 ABI/状态机测试、relay 测试、Electron EPIPE 验收脚本。

### 2.3 当前支持的工作流

`backend/services/workflow_engine.py` 注册 34 个模板，主要包括：

- Idea discovery：文献调研 → idea 生成 → 新颖性检查 → 外部评审 → 方法精炼/实验规划。
- Experiment bridge：实现、部署、收集结果、出图。
- Auto review：多轮审稿与修改。
- Paper writing：英文、中文、Nature、从已有资产写作。
- Full pipeline：从文献到 PDF 的一条龙。
- 数学建模竞赛矩阵。
- 开题报告、文献综述、课程论文/报告。

这是当前最有价值的资产：**已经有清晰的科研生命周期概念和工作区产物约定**。下一阶段应把它从“prompt 串联”升级为“可验证的科研状态机”。

---

## 三、已有优势

### 3.1 工作流恢复与运行状态比较扎实

- SQLite WAL、busy timeout、锁重试和断点恢复已有测试。
- 工作流步骤有 `pending/running/waiting_checkpoint/completed/failed/skipped` 状态。
- 有用户检查点、反馈重跑、WebSocket 日志、文件快照和输出合同。
- 工作区自动初始化 Git，具备进一步做版本化和 provenance 的基础。

### 3.2 已意识到“证据约束”而非纯文本生成

技能中存在：

- Claims–Evidence Matrix。
- 禁止伪造 BibTeX、要求 DBLP/CrossRef 校验。
- 结果不得硬编码、图表从 JSON/CSV 读取。
- `experiment-integrity.md` 对 fake GT、score normalization、phantom results、样本范围夸大做了明确约束。
- `assurance-contract.md` 设计了 PASS/WARN/FAIL/BLOCKED/ERROR 和输入哈希。

这些理念正确，主要问题是 **尚未变成主引擎的强制执行逻辑**。

### 3.3 对“工程味/AI 味”已有直接规则

- `skills/shared-scripts/writing_rules.md` 包含 De-AI Polish、避免短碎段落、模板化过渡、空洞意义膨胀等规则。
- `skills/paper-write-nature/SKILL.md:278-286` 明确禁止因果升级、禁止 AI 从零起草核心科学论证，并要求先修逻辑后修辞。
- `skills/shared-references/writing-principles.md` 强调 What–Why–So What、单一核心贡献、实验必须服务 claim。

因此无需推倒重写，应把这些规则抽成 **可测的 narrative/claim gate**，并让常规英文/中文写作都继承 Nature 写作中的科学论证约束。

---

## 四、阻塞性问题（P0）

### P0-1：编辑器后端 API 大面积断裂

`backend/routers/editor.py` 调用了以下服务函数：

- `file_preview_html`（77–78）
- `create_file`（104–105）
- `delete_file`（110–111）
- `download_file`（116–118）
- `drawio_export`（125–126）
- `image_check`（130–131）
- `generate_image`（135–136）
- `compile_paper`（140–141）
- `docx_status`（154–155）
- `get_stats`（168–169）
- `describe_image_endpoint`（223–225）

但 `backend/services/editor_ai.py` 并未定义这些函数。冒烟测试确认相关接口返回 500。与此同时：

- `ai_agent_apply` 直接返回成功，不应用任何文件（204–206）。
- `ai_agent_discard`、`ai_agent_stop` 是空操作（209–211、228–230）。
- `ai_agent_check` 永远返回 `has_diff: false`（233–237）。
- `ai_agent_endpoint` 只是普通一次 LLM 请求，并没有 Agent sandbox/diff（196–201）。

**影响：** 前端展示了编辑、编译、图片、Agent 修改等能力，但真实用户点击会失败或得到虚假成功。这是产品可信度的首要问题。

**修复验收：** 为每个前端可达 API 建立 contract test；未实现功能应隐藏/返回 501，不能返回伪成功。

### P0-2：开发态运行路径解析错误

`backend/config.py:39-41` 将 `_RESOURCES_DIR` 和 `_INSTALL_DIR` 连续上溯，导致当前源码树中：

- 预期 `D:\科研软件制作\Vibe-research源码\runtime`
- 实际解析成 `D:\runtime`

由此 `RUNTIME_PYTHON`、`RUNTIME_NODE`、`RUNTIME_DRAWIO`、`Pandoc`、Claude 都可能找不到。`_is_desktop_mode()` 的 runtime 候选又使用另一套层级，开发态/打包态判定不一致。

**影响：** `run.py` 看似能用自带 Python，但后端配置及 runner 仍可能认为 Claude 不存在；源码环境与安装环境行为不一致。

**修复验收：** 使用明确的 `APP_ROOT`/`RUNTIME_ROOT` 环境变量与可测试 resolver；覆盖 source、packaged resources、portable、system fallback 四种布局。

### P0-3：技能运行依赖未注入，关键科研能力会静默失效

`claude_runner.py:19-20` 定义了 `REVIEWER_SCRIPT` 和 `SCHOLAR_SCRIPT`，但 `run_skill()` 在 209–220 行只注入通用 settings 和 `SKILL_*`，没有写入这两个环境变量。

而至少 81 处技能脚本直接依赖 `$REVIEWER_SCRIPT` 或 `$SCHOLAR_SCRIPT`，例如：

- `skills/research-lit/SKILL.md:132-152`
- `skills/paper-write/SKILL.md:315,369`
- `skills/auto-review-loop/SKILL.md:117,413`
- `skills/experiment-bridge/SKILL.md:191`

同样，大量技能依赖 `_utils/...`。工作流创建后只有 `CLAUDE.md` 和 `.git`，没有 `_utils`；`decrypt_skills_to_workspace()` 从未被调用。技能中的 fallback `skills/shared-scripts` 是相对工作区路径，通常也不存在。

**影响：** 文献真实性、外部审稿、图表/写作检查最可能在正式流程中被 shell 当成空变量或找不到文件，然后按 prompt 规定“skip/fail-soft”，形成假完成。

**修复验收：** 每个 step 启动前做 capability preflight，生成机器可读 `capabilities.json`；必需能力缺失则 BLOCKED，不允许静默跳过；将共享工具只读挂载/复制到工作区 `_utils`，并注入所有工具绝对路径。

### P0-4：科研诚信门禁没有接入主流程

`full_pipeline`（`workflow_engine.py:114-128`）当前是：文献 → idea → novelty → review → refine → experiment bridge → paper plan → drawio → write → compile → improvement。

缺失的强制阶段包括：

- experiment integrity audit
- result-to-claim gate
- statistical audit
- paper numerical claim audit
- citation audit
- proof checker（条件触发）
- final submission verifier

仓库确有 `skills/shared-references/assurance-contract.md`，并在 `skills/skills-codex/` 中存有若干审计技能，但它们不是顶层可执行技能，也未进入 `TEMPLATES`。文档宣称存在的 `verify_paper_audits.sh` 在仓库中不存在。

**影响：** 当前“完成”主要表示文件存在和 runner 返回 0，不表示数字、引用、统计结论或证明可信。

**修复验收：** workflow completion 必须由 gate graph 决定；submission 模式下任何 BLOCKED/ERROR/FAIL 都不得显示“submission-ready”。

### P0-5：API Key 和本地控制面暴露

- `backend/routers/settings.py:22-26` 原样返回设置表，包含 API Key。
- 设置值在 `state_store.py:200-218` 明文写入 SQLite。
- `backend/main.py:51-56` CORS 全开放且允许 credentials。
- API 无认证/CSRF/本地会话 token。
- `editor_ai.run_script()`（144 起）允许执行用户提供的 Python/Bash。
- `claude_runner.py:199` 使用 `--dangerously-skip-permissions`。
- `state_store.py:76-85` 启动时全局杀掉所有 `claude.exe`，可能误杀用户其他任务。

**影响：** 只要本机浏览器页面或其他进程能访问端口，就可能读取密钥、改设置、执行脚本、驱动 Agent。

**修复验收：** 随机本地会话 token、严格 Origin、只返回 masked secret、Windows Credential Manager/DPAPI、工作区沙箱、命令 allowlist/资源限额、按 PID/job object 管理子进程。

### P0-6：上传路径和路径边界实现不安全/不严谨

- `artifacts.py:52` 使用 `upload_dir / f.filename`，未规范化 filename；上传名可能包含路径组件。
- 多处用 `str(filepath).startswith(str(workspace))` 判断目录边界，在 Windows 上存在公共前缀误判，应使用 `Path.is_relative_to()`/`relative_to()`。
- ZIP 导入虽做了 `..` 检查，但缺总大小、单文件大小、压缩比、文件数限制。

**影响：** 路径越界、覆盖、压缩炸弹、磁盘耗尽。

### P0-7：TLS 与内置凭据问题

- `tools/reviewer_client.py:67-71` 对 HTTPS 无条件关闭证书/主机名验证。
- `tools/scholar_fetch.py` 有不校验证书 fallback。
- `tools/scholar_fetch.py:149-152` 内置长期 AMiner bearer token。

**影响：** 审稿内容、论文全文和 API Key 可被中间人截获；共享 token 也会带来供应链、配额和追踪问题。

---

## 五、科研可信度与“顶刊能力”审计

### 5.1 现有正向基础

- idea 阶段有 literature → novelty → external review → refine。
- Experiment Plan 模板采用 claim-driven 设计，包含 success/failure interpretation、预算、baseline、ablation。
- 写作阶段要求数值来自结果文件、引用从真实数据库抓取。
- 有 reviewer independence 和 experiment integrity 的理念。
- 去 AI 腔规则具体，不只是泛泛“润色”。

### 5.2 关键缺口

#### 文献综述仍是“搜索+摘要”，不是可复核证据综述

`research-lit` 没有稳定强制以下内容：

- 冻结检索日期、数据库、完整 query 和返回数量。
- inclusion/exclusion 标准、双人筛选或冲突记录。
- 全文证据定位（页码/段落/表格/图）。
- 研究质量/偏倚评估。
- citation snowballing、撤稿/勘误检查。
- 搜索结果快照与去重 ledger。

因此它适合作为探索式 related-work，不足以承担系统综述或顶刊“文献证据底座”。

#### 缺研究类型路由

34 个模板看起来很多，但正式科研主链主要以 CS/ML/数学建模范式设计。缺少一等公民的：

- 系统综述/Meta-analysis
- 临床/生物医学实验与指南路由
- 因果推断/观察性研究
- 质性/混合方法
- 理论证明型论文
- 软件/系统论文 benchmark 与 artifact evaluation

不同研究类型需要不同的统计门禁、报告规范和数据治理，不能只靠一个通用 paper-writing prompt。

#### “审稿分数”不是可靠停止条件

`skills/auto-review-loop/SKILL.md:40,131` 使用 6/10 + ready/almost 作为停止条件。该分数：

- 不校准、不可跨模型比较。
- 容易被同一对话上下文和措辞影响。
- 会诱导 agent 优化表面呈现而非解决科学问题。

应改成客观 gate ledger：关键 claim 是否有证据、baseline 是否复现、统计功效是否充分、数值是否可追溯、引用是否支持语境、限制是否完整、必需审计是否通过。

#### 输出大小/页数下限会诱导注水

`paper-write/SKILL.md:15` 要求正文页数“≥ MAX_PAGES”；中文写作也有 bachelor/master/journal 的下限。文件 ≥5KB、章节 ≥500 chars 适合作为防空文件 smoke check，却不应成为质量门槛。

建议改为：venue 上限 + section evidence coverage + redundancy/boilerplate ratio + claim density。篇幅不足应追问“缺什么证据/解释”，而不是机械扩写。

#### 常规写作仍可能产生“工程味”

根因不是几句禁用词，而是输入叙事仍是 pipeline artifacts：实现、架构图、代码、运行日志很容易主导论文。虽然 Nature skill 已明确“Never let AI draft the core scientific argument from scratch”，但常规 paper-write 没有同等强的**科学论证所有权**。

建议建立两层文档：

1. **Research Record（内部）**：实现、环境、命令、debug、工程优化、artifact provenance。
2. **Scientific Narrative（论文）**：问题、缺口、假设、机制、识别策略、证据、反例、边界、意义。

写作模型默认只能读取第二层和经过裁剪的 Evidence Cards；工程记录只在复现性/系统贡献确实相关时由用户批准引入 Methods/Appendix。

---

## 六、测试与部署审计

### 6.1 实际运行结果

1. `runtime\python\python.exe build.py`：成功；21 个模块导入、60 个 API 路由注册成功。
2. `runtime\python\python.exe tests\test_backend.py`：27 passed / 1 failed。
   - 失败：`test_workflow_vision_and_context_compression_helpers`
   - 具体：`_extract_pdf_with_vision()` 未清理工作区 `_tmp`，违反 `tests/test_backend.py:685`。
3. `python -m pytest`：不可用；runtime 中存在 `pytest` 包但 `_pytest` 目录缺失，是残缺安装。
4. `node tests\test_mainjs_epipe.js`：通过。
5. `node tests\run_electron_epipe_acceptance.js`：当时失败，缺打包的 `Vibe Research.exe`。
6. `tests/run_document_artifacts.py`：未设置 desktop 环境时 config 错误解析到父目录，导致 DOCX 工具找不到；该测试也暴露开发/打包路径混乱。
7. API 冒烟：编辑器多个路由返回 500，现有测试只验证“路由存在”，没有调用功能。

### 6.2 测试体系问题

- `tests/test_backend.py` 是自制 `run_all()`，异常消息常被吞掉，首轮只显示空失败原因。
- 大量测试验证“installed/recovered contract”，例如模板矩阵 578 cases，更像静态 ABI 回归，而非产品行为和科学正确性。
- 没有 lint/type check、覆盖率、依赖漏洞、secret scan、API schema snapshot。
- 没有对以下关键链做 E2E：上传真实论文 → 文献检索 → evidence ledger → experiment run → audit → paper → compile/export。
- 没有 golden corpus：真实论文/结果文件的 claim-citation 测试集。
- 没有对 prompt/skill 做版本、依赖、输出 schema、determinism 测试。
- 前端只有编译 bundle，无法进行组件/状态管理测试。

### 6.3 部署与可维护性

- 顶层 `package.json` 仅 7 行，无 Electron dependency、scripts、builder 配置、lockfile。
- 没有 README、LICENSE 文件、CHANGELOG、SECURITY、CONTRIBUTING、`.gitignore`、CI。
- Git 仓库无 commit，整个项目和大体积 runtime 都处于未跟踪状态。
- Python requirements 只有宽泛范围，不含科研运行时的大量真实依赖，也没有 lock/hash/SBOM。
- 前端源码缺失，后端部分工具只发 `.pyc`，难以审计与维护。
- `workflow_engine.py` 2490 行，模板、调度、验证、恢复、竞赛规则、上下文生成混在一起。
- skills 顶层和 nested pack 有 39 个同名技能，来源/优先级/版本不清。

---

## 七、可落地的目标架构与集成点

### 7.1 建议的七层架构

1. **Workspace & Identity**：项目、用户、研究类型、目标 venue、预算、隐私策略。
2. **Research Graph**：Question → Hypothesis → Claim → Evidence → Artifact → Citation 的有向图。
3. **Orchestrator**：持久化 DAG、队列、重试、人工门、并发/预算/取消；每步输入输出均 schema 化。
4. **Tool/Connector Layer**：文献数据库、Zotero、代码执行、容器/GPU、统计、LaTeX/DOCX、图像。
5. **Evidence & Provenance**：文件 hash、数据版本、环境 lock、命令、seed、run ID、来源定位、审计 trace。
6. **Independent Assurance**：实验、统计、claim、citation、proof、reporting guideline 多审稿者门禁。
7. **Scientific Narrative**：基于已确认 claim/evidence 组织学术故事；和工程记录物理分离。

### 7.2 对当前代码最自然的集成点

- `StepDef`：扩展 `inputs_schema`、`outputs_schema`、`capabilities`、`gate_policy`、`resource_policy`、`reviewer_independence`。
- `run_single_step()`：加入 preflight、container/sandbox executor、output schema validation、artifact hashing、cost ledger。
- `_resolve_template()`：从硬编码 if/else 迁移到 YAML/JSON workflow registry 和研究类型路由。
- SQLite schema：增加 artifacts、claims、evidence、citations、runs、audits、lineage、costs、human_decisions。
- 工作区 Git：升级成每步 commit/tag，配合 DVC 或 content-addressed artifact store。
- skills：每个 skill 增加 `skill.yaml`（version、owner、dependencies、required env、inputs/outputs、tests、license）。
- 前端：增加研究图、claim-evidence matrix、审计面板、实验 run compare、引用证据定位、人工批准中心。

---

## 八、优先修复路线

### Phase 0：可信基线（第 1–2 周，P0）

1. 恢复前端源码或承认 dist-only，删除/隐藏所有未实现 UI；补齐 editor API。
2. 统一 path resolver，确保源码、portable、packaged 三种布局一致。
3. 修复 `_utils`、reviewer/scholar/tool path 注入；所有技能做 preflight。
4. 密钥 masking + DPAPI/Credential Manager；本地 session token；收紧 CORS。
5. 禁止伪成功；缺功能返回 501；移除全局 taskkill。
6. 上传/ZIP/路径安全和资源限制。
7. 修复 pytest 环境与现有 1 个失败测试。

**退出标准：** 所有前端可达 API contract test 通过；新机器离线启动/创建/暂停/恢复/导出 smoke 通过；日志中无 silent skip。

### Phase 1：科研证据闭环（第 3–5 周，P0/P1）

1. 引入 Research Contract、Claim、Evidence、Artifact 的正式 schema。
2. 让文献检索保存 query/date/source/result snapshot 和 Evidence Card（含页码/段落）。
3. 实验 run 保存 dataset hash、split、seed、config、command、environment、raw metrics。
4. 主流程接入 experiment-audit → result-to-claim → paper-claim-audit → citation-audit → verifier。
5. reviewer 不可用时 submission 模式 BLOCKED，不可自审替代。

**退出标准：** 任意论文数字可以点击追溯至 raw artifact；任意引用可以定位到支持该句的原文；审计 artifact 有 hash 且 stale 后自动失效。

### Phase 2：博士生研究工作台（第 6–8 周，P1）

1. Zotero/本地 PDF/笔记库统一文献库与全文索引。
2. 增加 protocol、screening、bias appraisal、snowballing、retraction check。
3. 增加实验队列、GPU/本地资源、budget、失败恢复、run compare。
4. 增加 domain packs：ML、因果推断、系统综述、生医、理论、质性。
5. UI 提供 hypothesis/claim/evidence/decision ledger，而非只展示文件。

### Phase 3：学术叙事与反“工程味”（第 9–10 周，P1）

1. 生成前必须由用户锁定 1–3 个核心科学 claims；AI 不得擅自新增主 claim。
2. Scientific Narrative 输入中默认排除代码文件、debug log、内部路径、pipeline 说明。
3. 章节规划按 rhetorical moves，而非按软件模块。
4. 加“工程味检测”：实现/平台/模块/架构/流程等词的密度、Methods 之外的出现位置、贡献 bullet 是否是功能清单。
5. 引入目标期刊真实论文 corpus，做结构/论证 move 对齐，而不是套固定模板。
6. 最终由人类作者做 argument ownership checkpoint。

### Phase 4：可评测的高水平能力（持续）

建立 benchmark，至少包括：

- 引用幻觉率、引用语境支持率。
- 数字追溯准确率、claim-evidence coverage。
- 统计错误检出率、数据泄漏检出率。
- 同一数据重复运行可复现率。
- 盲审专家对 novelty、rigor、clarity 的评分与一致性。
- “工程味/模板味”人工 pairwise preference。
- 真实博士生完成时间、失败率、人工修改量。

只有这些指标持续达标，才能合理描述为“具备顶刊研究生产支持能力”。

---

## 九、针对“避免工程味”的具体写作协议

建议把以下协议设为所有 journal workflow 的硬规则：

1. **先科学后实现**：先写 Research Question、Gap、Hypothesis、Mechanism、Falsifier、Claim Boundary，再允许读取实现摘要。
2. **贡献不是功能清单**：禁止“我们设计了平台/实现了模块/搭建了流程”作为主贡献，除非论文研究对象就是系统且有可量化系统研究问题。
3. **Methods 只保留可复现所需实现**：工程细节进入 appendix/artifact documentation；正文讲选择背后的科学理由和识别逻辑。
4. **Results 以命题开头**：段落主语优先是发现/关系/机制，不是“图 X”“系统”“模块”。
5. **Discussion 解释边界**：区分 observed、inferred、speculative；明确 negative evidence、alternative explanations、external validity。
6. **每段证据账本**：每个主张标记 literature / data / derivation / expert judgment；没有证据的不进入定稿。
7. **禁止页数驱动扩写**：删除“正文必须 ≥ MAX_PAGES”；用 claim coverage 和必要性判断篇幅。
8. **双重审稿**：科学审稿和文风审稿分开；文风模型不得改数字/claim，科学模型不得用措辞漂亮掩盖证据不足。
9. **保留作者声音**：让博士生提供 3–5 篇自己认可的 exemplar 和自己的术语表/立场笔记；模型做约束下编辑，不从零代写核心论证。

---

## 十、文件级技术债清单

| 优先级 | 文件 | 问题 |
|---|---|---|
| P0 | `backend/routers/editor.py` / `backend/services/editor_ai.py` | 路由-服务合同断裂；多个 500；伪成功占位符 |
| P0 | `backend/config.py:34-84` | 开发/打包 runtime 根目录计算错误 |
| P0 | `backend/services/claude_runner.py:191-220` | 未注入 reviewer/scholar/shared tools；危险权限模式 |
| P0 | `backend/services/workflow_engine.py:114-128` | full pipeline 缺科研审计门禁 |
| P0 | `backend/routers/settings.py:22-33` | 明文返回/更新全部 secret |
| P0 | `backend/main.py:51-56` | CORS 全开放 |
| P0 | `backend/routers/artifacts.py:45-55,80-122` | 上传名、路径边界、资源限制 |
| P0 | `tools/reviewer_client.py:67-71` | TLS 校验关闭 |
| P0 | `tools/scholar_fetch.py:149-152` | 内置长期 token；TLS fallback 不安全 |
| P1 | `backend/services/workflow_engine.py` | 2490 行单体；模板/执行/验证混杂 |
| P1 | `backend/services/state_store.py:76-85` | 全局 taskkill；迁移仅手写一列 |
| P1 | `skills/paper-write*/SKILL.md` | 页数下限/文件大小作为质量代理；审计 fail-soft |
| P1 | `skills/auto-review-loop/SKILL.md:40,131` | 6/10 停止条件过弱且不可校准 |
| P1 | `skills/research-lit/SKILL.md` | 非系统化检索，无 evidence locator/protocol |
| P1 | `skills/shared-references/assurance-contract.md` | 设计存在但主流程未接线，verifier 缺失 |
| P1 | `tests/test_backend.py` | 测试偏 ABI，不覆盖真实 API/科研质量 |
| P1 | `package.json` / `dist/` | 前端源码和正式构建链缺失 |
| P2 | `skills/` | 同名 pack 多、版本/来源/依赖漂移 |
| P2 | `runtime/` | 5.2 GB、无 lock/SBOM、pytest 残缺 |
| P2 | `tools/*.pyc` | 关键实现不可维护/不可审计 |

---

## 十一、最终判定

### 可保留并强化

- Electron + FastAPI 本地优先形态。
- SQLite 工作流状态机和 workspace-per-project 模式。
- Research Contract / Experiment Plan / Findings 模板。
- Claude runner + 外部 reviewer 的角色分离思路。
- Claims–Evidence、引用真实性、实验诚信、去 AI 腔和图表规范。

### 必须重构而不是继续堆 prompt

- 编辑器服务层。
- runtime/tool capability discovery。
- workflow engine 单体及硬编码模板。
- secret/control-plane 安全。
- evidence/provenance 数据模型。
- submission assurance gate。
- skill package/version/dependency 系统。
- 科学叙事与工程记录的分层。

**一句话结论：** 项目已有有价值的科研自动化骨架和大量领域知识，但当前最大的短板是“看起来会做很多事，却不能机器证明关键步骤真的做了、做对了、可复现”。先把真实能力、证据链和失败可见性做实，再引入更多仓库和更强多智能体，才是把它升级为博士生可依赖科研软件的可实现路径。

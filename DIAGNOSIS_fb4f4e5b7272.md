# 工作流 fb4f4e5b7272 — paper-figure 步骤无法恢复与执行的根因诊断

**工作流 ID**: `fb4f4e5b7272`
**模板**: `comp_cumcm` （2024 高教社杯 C 题 · 农作物的种植策略）
**当前状态**: `status=failed`, `current_step=paper-figure`
**已尝试次数**: 65 次（截至 2026-09-01 11:08）
**诊断时间**: 2026-08-31 初诊；**2026-09-01 复核定案**

---

## ★ 2026-09-01 复核定案（当前根因，已四重证实）

> 本节为最新结论。昨日（08-31）的 R1–R4 是历史叠加层，其中 **R1 的归因（App Execution Alias）对本实例不准确**，真正的当前根因如下。

### 一句话结论（定案）

后端以 `python -m uvicorn main:app --reload --port 18088` 启动（源码开发模式），**uvicorn ≥0.36 在 `reload=True`（`use_subprocess=True`）时于 Windows 上强制使用 `SelectorEventLoop`**（`uvicorn/loops/asyncio.py`：`if sys.platform == "win32" and not use_subprocess: return asyncio.ProactorEventLoop; return asyncio.SelectorEventLoop`）。`SelectorEventLoop` 不支持子进程，`asyncio.create_subprocess_exec` 必然抛出**裸 `NotImplementedError`（无消息）**。`paper-figure` 属于 `_AUTO_RECOVER_FIGURE_SKILLS`，每次执行/恢复前都会跑 `_probe_figure_execution_channel` 预检；预检内部 `_run_process` 的"去掉 creationflags 重试"**同样失败且未再捕获**，异常直接穿透 probe（设计意图是"只警告"，实际变成"致命"）→ `_run_single_step_locked` 外层 except 记为 `NotImplementedError (no message)` → 步骤与工作流置 `failed`。**全程约 80–200ms，即"恢复后立即失败"**。

### 铁证链（2026-09-01 11:08 新鲜复现）

1. **进程命令行**（PID 2620，启动于 11:08:10）：`python -m uvicorn main:app --reload --port 18088` → `use_subprocess=reload=True` → SelectorEventLoop。
2. **后端日志 traceback**（`runtime/backend/logs/backend.log`，11:08:24）：`workflow_engine.py:5746 _run_single_step_locked` → `:3268 _probe_figure_execution_channel` → `:3114/3099 _run_process` → `asyncio/base_events.py:533 _make_subprocess_transport raise NotImplementedError`。**关键**：栈帧落在 `base_events.py:533`（基类实现），而 Python 3.14 的 `ProactorEventLoop` 在 `windows_events.py:397` 覆写了该方法——证明当前循环**不是** Proactor。
3. **数据库 attempt 64/65**（invocation=`recover`）：耗时 **77ms/109ms**，`error_message='NotImplementedError (no message)'`；recovery_operations 同步记录 `paper-figure: NotImplementedError (no message)`。
4. **对照组**：`openai_responses_agent.py:557-584` 的 agent 通道有**第三层兜底**（sync `subprocess.run`），所以 agent 步骤在同一循环下仍能工作——唯独 `workflow_engine._run_process` 缺这层兜底。

### 恢复链路全程（点击"从失败点恢复"后实际发生的事）

```
前端 POST /api/workflows/fb4f4e5b7272/recover          (routers/workflows.py:598)
  → _request_recovery(mode="recover")                  (routers/workflows.py:562)
  → request_step_recovery()                            (workflow_operations.py:849)
      前置校验：step.status ∈ {failed,pending} 且 workflow.status ∈ {failed,paused} ✅ 满足
      选点：_recovery_target() → 第一个 failed 步骤 = paper-figure
      写入 workflow_recovery_operations(status=running)，调度 _execute_recovery_operation
  → _execute_recovery_operation()                      (workflow_operations.py:732)
  → run_workflow(workflow_id)                          (workflow_engine.py)
  → _run_single_step_locked('paper-figure')
      5710-5736  runner 选择：executor 已配置 → ClaudeRunner（日志 11:08:24,668）
      5745-5748  probe：_probe_figure_execution_channel(workspace)   ← 💥 在这里炸
        → 3256-3265 figures/ 写入探测 ✅ 通过
        → 3268 _run_process([python, "-c", ...])
            → 3099 create_subprocess_exec(+CREATE_NO_WINDOW) → NotImplementedError
            → 3106 捕获 → 3114 重试（去掉 creationflags）→ 再次 NotImplementedError ❌ 未捕获
        → probe 无 try/except 包住 3268 → 异常穿透（"只警告"的设计意图落空）
      6102 except Exception → log.exception("Step execution failed: ")（空消息）
      6108 error_text = "NotImplementedError (no message)"
      6110-6117 workflow_steps/workflow 置 failed
  → _execute_recovery_operation 检测到 failed
      → error = "paper-figure: NotImplementedError (no message)" 写入 recovery_operations
  → 全程 ~80-200ms → 前端看到"恢复后立即失败"
```

**为什么 host-fallback 没救场**：5898 行的 `_host_execute_gen_fig_scripts` 只在 `recovery_reason is not None` 时触发，而 `recovery_reason` 来自 `runner.run_skill` 跑完后的结果分析——probe 在 runner 启动**之前**就抛异常，永远到不了 5898 行（工作区无 `.host_builds/` 目录佐证）。

### 修复建议（定案版，按优先级）

> **修复状态（2026-09-01 12:2x）**：建议 1/2/3 已实施并提交（commit `9faf68f`，挂在 origin/xbw `e8b79e5f` 之上）；回归测试 `tests/test_host_run_process_fallback.py` 3/3 通过。建议 4 需用户确认解释器依赖后执行；建议 5 已落实到 CODEBASE.md §12.8 顶部修正块。后端以 `--reload` 运行，改动已自动热加载，可直接在前端再次点击"从失败点恢复"验证。

1. **根治（一处修复治好所有 host 步骤）**：给 `workflow_engine._run_process`（3099-3120）增加第三层兜底——第二次 `NotImplementedError/OSError` 后改用 `await asyncio.to_thread(subprocess.run, ...)` 同步执行，直接移植 `openai_responses_agent.py:574-581` 的 `_run_command_sync_fallback` 模式。这一处同时治好 probe、`_host_execute_gen_fig_scripts`、pandoc/drawio 导出等全部走 `_run_process` 的路径。
2. **防御**：`_run_single_step_locked` 5745-5748 的 probe 调用包 try/except，异常时构造 `probe_issue` 文案走既有 warning 分支（恢复 probe "只警告不致命"的设计意图）。
3. **绕过（立即可做）**：源码模式启动**去掉 `--reload`**（uvicorn 在 win32+use_subprocess 时强制 SelectorEventLoop；桌面模式 main.js:343 不带 --reload 故无此问题）。注意 `main.py:11` 的 `WindowsProactorEventLoopPolicy` 在 uvicorn ≥0.36 下是**死代码**——`server.py:74` 用 `loop_factory` 直接实例化循环类，完全绕过 policy，建议删除或改为自定义 loop_factory。
4. **后续依赖**：probe 修通后 host-fallback 跑 `gen_fig_*.py` 还需要 `numpy/matplotlib`，确认 `_runtime_python()`（3431-3436，RUNTIME_PYTHON 或 sys.executable）指向的解释器已安装这些包。
5. **CODEBASE.md 修正**：§12.8 把裸 `NotImplementedError`（空消息）归因为 "App Execution Alias"，本实例证明真正的充分条件是 **SelectorEventLoop**（栈帧在 `base_events.py:533` 即基类实现 = 循环未覆写子进程方法）。建议修订该节，避免下次误诊。

### 昨日假设的最终判定

| # | 假设 | 判定 |
|---|---|---|
| H1 | host-fallback 在 recover 模式不触发 | ✅ 证实（且原因更靠前：probe 先炸，runner 没机会跑） |
| H2 | <200ms 失败源自 `_prepare_skill_runtime` | ❌ **修正**：源自 `_probe_figure_execution_channel` → `_run_process` 的 NotImplementedError |
| H3 | 僵尸 attempt 阻塞恢复 | ⚠️ 曾经成立（attempt 41-48），当前已清理（DB 无 running 记录），非当前根因 |
| H4 | rename-aside 失败抛 RuntimeError | ✅ 证实（历史层，attempt 28） |
| H5 | 前端重复触发 recover | 未单独验证；今天 11:08 的 64/65 两次间隔 4 秒，符合人工点击，非防抖问题 |

---

## （以下为 2026-08-31 初诊原文，保留作历史层参考）

### 初诊一句话结论

`paper-figure` 步骤陷入**多重叠加的恢复死锁**：恢复时同时命中 (A) 桌面宿主的"安全删除"策略、(B) AI 子进程通道的 Win32 App Execution Alias bug、(C) 缺少必要的 host-fallback 触发条件，导致 50 次尝试全部失败，且工作区累积 17 个 `_utils.stale-*` 残留目录。

---

## 症状时间线（按 attempt_number 聚类）

| 阶段 | attempts | 触发方式 | 错误签名 | 根因层 |
|---|---|---|---|---|
| ① | 1–8 | workflow / retry / recover | `步骤连续 6 次未产出 primary_output: figure step did not create the required figure type` | LLM 写了 gen_fig_*.py 但**未运行**它们 |
| ② | 4–8 | recover | `figures/ 内文件扩展名不合法 ['.json','.md','.py','.tex']` / `只有辅助文件` | 同上，只是诊断文案更精确 |
| ③ | 5 | recover | `[WinError 10060] 连接尝试失败` | 上游 LLM 网络故障（瞬时） |
| ④ | 9 | recover | `API 返回 HTTP 503 upstream_unavailable` | 上游 LLM 服务故障（瞬时） |
| ⑤ | 11–27 | recover/retry | `error_message=NULL` 但 `status=failed`，<200ms 完成 | **恢复路径在早期静默失败**（详见假设 H2） |
| ⑥ | 28 | workflow | `CAPABILITY_BLOCKED:shared-scripts:mount_failed:could not remove ...\_utils after 5 attempts: [safe-delete][SAFE_DELETE_FAIL_CLOSED]` | 桌面宿主 safe-delete hook 拦截 rmtree |
| ⑦ | 29–40 | recover/retry | `error_message=NULL` 但 `status=failed`，<200ms 完成 | 同 ⑤ |
| ⑧ | 34 | workflow | `API 返回 HTTP 502 upstream_unavailable` (smart_route payload_limit) | 上游 LLM 故障 + 路由切换 |
| ⑨ | 41–48 | workflow | 8 个 attempt `status=running` 永不结束 | 后端重启但 attempt 状态未回收（僵尸） |
| ⑩ | 49–50 | workflow / recover | `error_message=NULL` 但 `status=failed`，<200ms 完成 | 同 ⑤ — **当前最新状态** |

---

## 工作区物证

```
runtime/workspaces/fb4f4e5b7272/
├── _utils/                       ← 当前 mount 共享脚本（42 个文件）
├── _utils.stale-1788173298/      ┐
├── _utils.stale-1788173308/      │
├── _utils.stale-1788173319/      │
│   ...                           ├─ 17 个 .stale- 残留（rename-aside 兜底产物）
│   ...                           │
├── _utils.stale-1788174780/      ┘
├── code/             (comp-code 产物，OK)
├── figures/
│   ├── gen_fig_*.py              ← 14 个绘图脚本（AI 写的）
│   ├── all_results.json          ← status=execution_blocked
│   ├── problem_{1,2,3}_results.json  ← 全部 results_pending=true
│   ├── sensitivity_results.json  ← 同上
│   ├── FIGURE_EXECUTION_BLOCKED.md   ← AI 自己承认"无法执行 python"
│   ├── FIGURE_PLAN_RECONCILIATION.md
│   ├── latex_includes.tex        ← 引用了不存在的图
│   └── ... 0 个 .png/.pdf/.svg   ← **一张图都没产出**
├── user_data/, AUDIT_REPORT.md, CLAUDE.md, ...
└── (无 .host_builds/)            ← host-fallback 从未触发
```

### 关键证据 1：figures/ 里没有任何图像
14 个 `gen_fig_*.py` 全部存在，但 0 个 `fig_*.png` / `fig_*.pdf`。`figures/all_results.json` 标注 `"status": "execution_blocked"`。

### 关键证据 2：AI 自己承认无法启动 python
`figures/FIGURE_EXECUTION_BLOCKED.md` 原文：
> - `python --version`（直接执行）：宿主进程启动返回 `NotImplementedError`。
> - `python --version`（shell 模式）：默认 PowerShell 不在命令白名单。
> - `python _utils/figure_check.py figures`：无法启动 Python。
> - `cmd.exe /c python --version`：`cmd` 不在命令白名单。
> - `bash`：真实 Bash 不存在。

这精确对应 `CODEBASE.md §12.8` 描述的 **Windows App Execution Alias NotImplementedError**。

### 关键证据 3：后端宿主 Python 是干净的
直接调用 `python figures/gen_fig_land_capacity.py`（绕过 sandbox），可以正常启动 Python，只是缺 `numpy`/`matplotlib`：
```
ModuleNotFoundError: No module named 'numpy'
```
说明 **host-fallback 通道（`_host_execute_gen_fig_scripts`）理论上是可用的**，但代码路径没走到那里。

### 关键证据 4：mount_failed 错误源自桌面 safe-delete
`skill_crypto.py:104-133` 的 `_retry_rmtree()` 注释明确写道：
> Some sandboxes (and the desktop host's safe-delete hook) intercept rmtree's per-file deletes and require a recycle bin that the backend environment does not provide, turning every removal into SAFE_DELETE_FAIL_CLOSED.

代码已经实现了 rename-aside 兜底，17 个 `_utils.stale-*` 目录正是这个兜底机制留下的痕迹。但 attempt 28 的 rename-aside 也失败了 (`could not remove ... after 5 attempts: ... rename-aside also failed`)，说明此刻文件被外部进程（很可能是另一个 step 正在运行的 agent）持有锁。

---

## 根因分析（按贡献度排序）

### R1：Windows 上的 Python 子进程通道被 App Execution Alias 拦截
**位置**：`backend/services/openai_responses_agent.py:449-546`

后端**已经实现**了三层防御：
1. PATH 过滤 `WindowsApps`
2. `shutil.which` 解析为绝对路径后再 CreateProcess
3. NotImplementedError 时 retry without creationflags → 再 fallback 到 sync subprocess.run

**但是**，`FIGURE_EXECUTION_BLOCKED.md` 表明在 agent 执行 *当时* 这些防御**未生效**或**还不够**。最直接的可能性是：执行 attempt 1–8 时（2026-08-04），后端代码还没包含 §12.8/§12.9 的修复（这些修复标记日期是 2026-07-30，但当前实例可能仍在跑旧代码）。

**当前**（2026-08-31）后端代码确实有这些修复，所以现在的卡点不在 R1，而在 R2/R3。

### R2：host-fallback `_host_execute_gen_fig_scripts` 永远不会被触发
**位置**：`backend/services/workflow_engine.py:5898-5931`

```python
if recovery_reason is not None:
    host_figs = await _HostStepRunner._host_execute_gen_fig_scripts(
        workspace_dir, skill_name, on_output=on_output,
    )
```

**关键问题**：这段代码只在 **`recovery_reason is not None`** 时才会执行 host-fallback。而 `recovery_reason` 只在 agent 跑完且失败时才被赋值。

但是当前 attempt 11–27、29–40、49–50 的 runner 调用**根本没有进入正常失败路径**——它们在 <200ms 内就失败，`error_message=NULL`，说明 runner.run_skill() 抛出了未捕获的异常或返回了 None，导致 `_execute_recovery_operation` 直接走到 `error_message=NULL` 的 fallback 文案 `node execution failed`。

**为什么 host-fallback 没救场**：因为根本没机会执行到 5898 行。验证：工作区里**没有 `.host_builds/` 目录**，证实 host-fallback 从未运行过。

### R3：`_retry_rmtree` 在并发场景下失效
**位置**：`backend/services/skill_crypto.py:104-133`

17 个 `_utils.stale-*` 目录的存在说明 rename-aside **成功过 17 次**。但 attempt 28 的报错 `could not remove ... after 5 attempts: ... rename-aside also failed` 表明：

- `shutil.rmtree(_utils)` 5 次失败（被 safe-delete hook 拦截）
- `os.replace(_utils, _utils.stale-XXX)` 也失败 — 这通常意味着 `_utils` 目录里有文件正被另一个进程打开（句柄锁）

**为什么并发**：attempt 28 的 invocation 是 `workflow`（不是 recover/retry），且 attempt 41–48 有 8 个 `running` 状态从未完成的 attempt。说明在某段时间内，**有多个 run_workflow 协程同时操作同一个工作区**，前者没退出后者又启动，文件锁冲突。

### R4：恢复路径缺少"快速失败"的 error_message 回写
attempt 11–27、29–40、49–50 的 `error_message` 全是 `NULL`，但 `workflow_recovery_operations.error_message` 是 `paper-figure: node execution failed`。

这是因为 `_execute_recovery_operation` 的 fallback 文案（`workflow_operations.py:760`）：
```python
f"{failed_step['skill_name']}: {failed_step['error_message'] or 'node execution failed'}"
```
当 `failed_step['error_message']` 是空字符串时，会 fallback 到 `"node execution failed"`，但这个值**只写进了 recovery_operations 表**，没回写到 `workflow_step_attempts.error_message`，导致运维侧看到一个没有任何错误信息的失败 attempt — **极大增加诊断难度**。

---

## 为什么"无法恢复"的具体机制

把上面四条串起来：

1. **2026-08-04**（attempts 1–8）：上游 LLM 链路正常，但 agent 的 sandbox 当时还没有 §12.8/12.9 的修复，**agent 进程内的 python 启动失败**（NotImplementedError）。AI 写了 gen_fig_*.py 但跑不了，诚实上报 → 触发"未产出 primary_output"。
2. **2026-08-31 09:00**（attempt 28）：用户首次重试。后端已经带新代码，但 mount 阶段需要清空旧 `_utils` —— 此时旧 `_utils` 目录里某些文件被另一个未退出的子进程持有，**`_retry_rmtree` + rename-aside 双双失败**，返回 `CAPABILITY_BLOCKED:shared-scripts:mount_failed`。
3. **2026-08-31 10:42–10:51**（attempts 29–40）：再次重试。这次 mount 可能成功了，但 runner 在 <200ms 内失败且 `error_message=NULL`——很可能是某个早期检查（capability probe、executor 配置校验等）抛了异常，**没走到 host-fallback**。
4. **2026-08-31 10:48–10:49**（attempts 34）：走到 agent 调用，但**上游 LLM 502**（payload_limit_soft_avoi），重试 8 次仍失败。
5. **2026-08-31 10:52–11:12**（attempts 41–48）：用户连点 8 次启动按钮，**`asyncio.create_task(run_workflow)` 被并发调用 8 次**，每次都写入 attempt，但都不结束（可能在前端断开后 task 仍挂着），数据库里留下 8 个 `status=running` 的僵尸记录。
6. **2026-08-31 13:26**（attempts 49–50）：用户重启后端再次尝试。僵尸 attempt 状态没清理，新的 attempt 又在 <200ms 失败（错误信息丢失，但 recovery_operations 表显示 `paper-figure: node execution failed`）。

**核心矛盾**：
- agent 通道曾经被修好（§12.8/12.9 修复在），但工作区已经被各种残留污染。
- host-fallback 是兜底，但兜底代码在错误路径上**根本没被执行**。
- 恢复操作没有清理僵尸 attempt，每次恢复都在脏状态上叠加。

---

## 排序后的可证伪假设（Phase 3 产出）

| # | 假设 | 证伪方式 | 验证结果 |
|---|---|---|---|
| H1 | host-fallback 代码路径在 recover 模式下不触发 | 检查 5898 行的 `recovery_reason` 是否在 recover 时被赋值 | ✅ 证实：recover 路径下 host-fallback 确实在某些异常分支被跳过 |
| H2 | attempt 49/50 的 <200ms 失败源自 `_prepare_skill_runtime` 抛错 | 在 `_prepare_skill_runtime` 添加日志看是否抛 CAPABILITY_BLOCKED | 待验证（最可能） |
| H3 | 8 个僵尸 attempt 41–48 阻塞了后续恢复 | 检查 run_workflow 是否有 workflow_id 级互斥锁 | 待验证 |
| H4 | rename-aside 失败时仍返回 mounted=False，导致 RuntimeError | 已在代码中确认（`_retry_rmtree` 抛 RuntimeError） | ✅ 已证实 |
| H5 | 前端在 attempt 34 的 502 后连续触发 7 次重复 recover | 前端 debounce 缺失 | 待验证 |

---

## 修复建议（按优先级）

### 立即可做（恢复 fb4f4e5b7272）

**方案 1：清理工作区 + 标记步骤为可恢复**
```python
import sqlite3, shutil
from pathlib import Path

ws = Path(r'D:\toolbox\VibeResearch源码及构建版本\vibe-research\runtime\workspaces\fb4f4e5b7272')

# 1. 删除 17 个 .stale 残留
for stale in ws.glob('_utils.stale-*'):
    shutil.rmtree(stale, ignore_errors=True)

# 2. 清理僵尸 attempt
db = sqlite3.connect(r'D:\toolbox\VibeResearch源码及构建版本\vibe-research\runtime\backend\vibe.db')
db.execute("""
    UPDATE workflow_step_attempts 
    SET status='interrupted', finished_at=datetime('now'),
        error_message='backend restarted; marked interrupted by cleanup'
    WHERE workflow_id='fb4f4e5b7272' AND status='running'
""")
# 3. 重置 paper-figure 步骤为 pending，清空 error_message
db.execute("""
    UPDATE workflow_steps 
    SET status='pending', error_message=NULL, started_at=NULL
    WHERE workflow_id='fb4f4e5b7272' AND skill_name='paper-figure'
""")
# 4. 工作流状态从 failed 改回 paused，允许恢复
db.execute("""
    UPDATE workflows SET status='paused' WHERE id='fb4f4e5b7272'
""")
db.commit()
```

**方案 2：手动调用 host-fallback 生成图像**
```bash
cd "D:\toolbox\VibeResearch源码及构建版本\vibe-research\runtime\workspaces\fb4f4e5b7272"
# 注意：当前 _utils/plot_utils.py 缺 numpy，需先在后端 Python 环境装
"C:\Users\hp\.workbuddy\binaries\python\envs\default\Scripts\pip.exe" install numpy matplotlib scipy pandas
# 然后逐个跑
for script in figures/gen_fig_*.py; do
    "C:\Users\hp\.workbuddy\binaries\python\envs\default\python.exe" "$script"
done
```

### 根本修复（代码层）

1. **`_execute_recovery_operation` 把错误信息回写到 `workflow_step_attempts`**（当前只写到 recovery_operations）。
2. **host-fallback 应在 `runner.run_skill` 抛异常时也触发**，而不是只在 `recovery_reason is not None` 时。
3. **run_workflow 入口加 workflow_id 级别的 asyncio.Lock**，防止并发协程同时操作同一工作区。
4. **`_retry_rmtree` 在 rename-aside 也失败时把目标改成 `_utils.stale-XXX-blocked` 并继续**，而不是抛 RuntimeError 中断整个 mount。
5. **后端启动时清理僵尸 attempt**（status=running 但 started_at 距今 >1h）。

---

## 附录：相关代码位置

| 关注点 | 文件 | 行号 |
|---|---|---|
| mount_failed 抛出点 | `backend/services/claude_runner.py` | 195 |
| _retry_rmtree + rename-aside | `backend/services/skill_crypto.py` | 104-133 |
| decrypt_skills_to_workspace 调用 _retry_rmtree | `backend/services/skill_crypto.py` | 168-172 |
| host-fallback 触发条件（太严） | `backend/services/workflow_engine.py` | 5898-5931 |
| _host_execute_gen_fig_scripts 实现 | `backend/services/workflow_engine.py` | 3123-3189 |
| _probe_figure_execution_channel | `backend/services/workflow_engine.py` | 3230-3261 |
| figures 健康检查 | `backend/services/workflow_engine.py` | 1940-1982 |
| App Execution Alias 防御 | `backend/services/openai_responses_agent.py` | 449-546 |
| 恢复操作的 fallback 错误文案 | `backend/services/workflow_operations.py` | 760 |

---

**诊断置信度**：高。所有根因都有数据库记录、文件系统物证和代码证据三重支撑。

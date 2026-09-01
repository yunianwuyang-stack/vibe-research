# 工作流 ec37c73b4a54 恢复失败诊断报告

**工作流 ID:** `ec37c73b4a54`  
**模板:** `comp_cumcm`  
**标题:** NIPT 的时点选择与胎儿的异常判定  
**当前状态:** `paused`  
**当前步骤:** `comp-code` (status: `pending`)  
**诊断时间:** 2026-07-31 02:36 UTC

---

## 症状总结

用户报告工作流无法恢复或重启，并遇到 **"fail to fetch"** 错误。

## 诊断发现

### 1. 数据库状态

查询数据库发现：

**工作流步骤状态：**
```
00  comp-prob-analysis    completed
01  comp-modeling         completed
02  comp-code             pending    ← 当前停在这里
03  paper-figure          pending
04  paper-figure-html     pending
05  comp-paper-zh         pending
06  comp-compile-zh       pending
```

**最近 5 次恢复操作（全部失败）：**
- 时间：2026-07-31 01:53:05 ~ 01:53:15 (10秒内连续5次)
- 模式：`recover`
- 状态：全部 `failed`
- 失败原因：**完全相同**

```
[Errno 2] No such file or directory: 'user_data/附件.xlsx.txt'
```

**步骤尝试记录：**
- `comp-code` 最近一次尝试：`attempt_number=3`, `invocation='recover'`, `status='interrupted'`
- 上一次正常尝试失败原因：`API 返回 HTTP 503`（上游 AI 服务不可用）

**工作区文件：**
```
workspace: D:\toolbox\VibeResearch源码及构建版本\vibe-research\runtime\workspaces\ec37c73b4a54
user_data/ 目录存在，包含文件：
  - C附.pdf
  - C附.pdf.txt
  - 附件.xlsx
  - 附件.xlsx.txt  ← 文件实际存在！
```

### 2. 根本原因分析

#### 问题 1：FileNotFoundError 的真正原因

**矛盾点：**
- 错误信息：`No such file or directory: 'user_data/附件.xlsx.txt'`
- 实际情况：该文件**确实存在**于工作区

**根本原因：**

错误路径 `'user_data/附件.xlsx.txt'` 是一个**相对路径**（不是绝对路径）。这意味着代码尝试相对于**当前工作目录（CWD）**而非工作区目录打开文件。

查看 `backend/services/workflow_engine.py` 第 775 行：

```python
grouped.setdefault(role, []).append(f"user_data/{Path(relative).as_posix()}")
```

这里构造的路径是字符串形式的相对路径，后续如果直接用于文件操作（如 `open(path)` 或 `Path(path).read_text()`）而不先与工作区目录拼接，就会相对于 Python 进程的 CWD 解析，导致找不到文件。

**失败时机：**
- 恢复操作在 <1 秒内失败（started_at 到 finished_at 仅 300~500ms）
- 步骤 `comp-code` 状态保持 `pending` 未变化
- 说明错误发生在 `run_workflow()` 的**初始化阶段**，在实际执行步骤之前

**可能的触发位置：**
- `_resolve_template()` — 解析模板时可能读取输入文件
- `_generate_claude_md()` — 生成 CLAUDE.md 时可能读取输入文件
- 或其他在步骤循环之前的初始化代码

#### 问题 2："fail to fetch" 的含义

"fail to fetch" 是浏览器 `fetch()` API 在**无法建立网络连接时**抛出的 `TypeError`。这通常意味着：

1. **后端未运行** — FastAPI 服务在 port 18088 未启动
2. **后端崩溃** — 在处理请求过程中 Python 进程崩溃

**在本案例中的分析：**

从数据库记录看，5 次恢复操作**全部被记录**，说明：
- POST `/api/workflows/ec37c73b4a54/recover` 请求**到达了后端**
- 后端返回了 HTTP 202 (Accepted)
- 后台任务启动并立即失败
- 失败状态被正确记录到数据库

这说明用户**当时**的 "fail to fetch" 不是恢复操作本身的 HTTP 调用，而可能是：

1. **事件流连接失败** — SSE `/api/workflows/operations/events` 无法连接
2. **后端在处理其他请求时崩溃** — 例如轮询工作流详情时后端崩溃
3. **用户描述不精确** — 实际看到的可能是 "恢复操作失败" 的通知，而非网络错误

**当前状态（诊断时刻）：**

如果用户**现在**尝试恢复/重启仍然失败，最可能的原因是：

- **后端未启动** — 需要运行 `python -m uvicorn main:app --reload --port 18088`（开发模式）或启动桌面应用
- **后端自动恢复机制触发崩溃** — 启动时 `lifespan` 中的 `resume_interrupted_operations()` 可能会尝试恢复这个工作流，导致同样的 FileNotFoundError

### 3. 为什么恢复操作连续失败 5 次

前端 `api.ts` 中的 `recoverWorkflow` 函数包含重试逻辑：

```typescript
export const recoverWorkflow = async (workflowId: string, reason: string) => {
  for (let attempt = 0; attempt < 3; attempt++) {
    try {
      return await api<...>(`/api/workflows/${...}/recover`, {...});
    } catch (e) {
      if (attempt < 2) await new Promise(r => setTimeout(r, 1000 * (attempt + 1)));
      else throw e;
    }
  }
};
```

这会重试 3 次（attempt 0, 1, 2），间隔 1秒 和 2秒。但数据库有 5 条记录，说明：
- 用户进行了至少 2 次独立的恢复尝试
- 每次尝试，前端重试了多次（可能部分成功返回 202，但后台立即失败）

---

## 修复方案

### 方案 A：修复相对路径问题（根本解决）

**需要修改的代码位置：**

找到所有使用 `_input_role_entries()` 返回的路径字符串并直接打开文件的代码，将其改为：

```python
# 错误示例（相对路径）
path_str = "user_data/附件.xlsx.txt"
content = Path(path_str).read_text()  # ❌ 相对于 CWD

# 正确示例（绝对路径）
workspace = Path(wf["workspace_dir"])
path_str = "user_data/附件.xlsx.txt"
content = (workspace / path_str).read_text()  # ✅ 相对于 workspace
```

**或者修改 `_input_role_entries()` 返回绝对路径：**

```python
def _input_role_entries(workspace: Path) -> Dict[str, List[str]]:
    root = Path(workspace) / "user_data"
    manifest_path = root / "_input_manifest.json"
    # ...
    for relative, metadata in manifest.get("files", {}).items():
        # ...
        role = str(metadata.get("role") or "material")
        # 返回绝对路径而非相对路径
        grouped.setdefault(role, []).append((root / relative).as_posix())
    return {role: sorted(set(paths), key=str.lower) for role, paths in grouped.items()}
```

但这会影响其他使用这些路径的代码（如 CLAUDE.md 生成），需要全局评估。

**推荐做法：**

1. 在 `workflow_engine.py` 中搜索所有使用 `_input_role_entries()` 结果的位置
2. 确保在打开文件时都使用 `workspace / path_str` 而非 `Path(path_str)`
3. 或者在 `run_workflow()` 开始时执行 `os.chdir(workspace)` 切换工作目录（但这可能影响其他并发工作流）

### 方案 B：临时绕过（不推荐，但可快速恢复）

**如果需要立即恢复这个工作流：**

1. **手动修改步骤状态，跳过 comp-code：**

```python
import sqlite3
db = sqlite3.connect('runtime/backend/vibe.db')
db.execute("""
    UPDATE workflow_steps 
    SET status='skipped', completed_at=datetime('now'), error_message='手动跳过以绕过文件路径问题'
    WHERE workflow_id='ec37c73b4a54' AND skill_name='comp-code'
""")
db.commit()
db.close()
```

2. **然后手动完成 comp-code 的工作：**
   - 在工作区 `code/` 目录中手动编写或放置代码
   - 在 `figures/` 目录中放置 `all_results.json`

3. **恢复工作流继续执行后续步骤**

**警告：** 这会跳过 AI 生成代码的步骤，需要人工补充产出物。

### 方案 C：检查并修复 `_generate_claude_md()` 或 `_resolve_template()`

这两个函数在 `run_workflow()` 初始化时被调用，可能是直接读取相对路径的位置。

**诊断步骤：**
1. 在这两个函数中添加日志或断点
2. 检查是否有 `open()` 或 `Path().read_text()` 使用了相对路径
3. 修复为绝对路径拼接

---

## 立即行动建议

### 如果用户需要**恢复这个特定工作流**：

1. **确认后端正在运行：**
   ```bash
   # 开发模式
   cd backend
   python -m uvicorn main:app --reload --port 18088
   
   # 或启动桌面应用（会自动启动后端）
   ```

2. **检查后端日志：**
   - 查看控制台输出，确认是否有 `FileNotFoundError` 异常
   - 如果看到异常堆栈，记录触发异常的具体代码位置

3. **临时修复（如果急需结果）：**
   - 使用方案 B 跳过 `comp-code` 步骤
   - 手动补充代码和结果文件
   - 恢复工作流继续执行

### 如果用户需要**根本修复这个 bug**：

1. **定位文件读取的具体代码：**
   ```bash
   cd backend/services
   grep -n "user_data/" workflow_engine.py | grep -E "open\(|read_text\(|read_bytes\("
   ```

2. **检查 `_generate_claude_md()` 和 `_resolve_template()` 的实现：**
   - 搜索这两个函数的定义
   - 查看是否有直接使用相对路径 `"user_data/..."` 的文件操作

3. **应用修复：**
   - 将所有相对路径改为 `workspace / relative_path`
   - 重启后端
   - 重新尝试恢复

4. **测试修复：**
   ```bash
   # 清除失败的恢复操作记录（可选）
   python -c "
   import sqlite3
   db = sqlite3.connect('runtime/backend/vibe.db')
   db.execute('DELETE FROM workflow_recovery_operations WHERE workflow_id=?', ('ec37c73b4a54',))
   db.commit()
   "
   
   # 然后从 UI 重新尝试恢复
   ```

---

## 相关代码位置

**关键文件：** `backend/services/workflow_engine.py`

**关键函数：**
- `_input_role_entries()` — 第 755 行，返回相对路径字符串
- `run_workflow()` — 第 5718 行，工作流主循环
- `_generate_claude_md()` — 第 5747 行调用（需要查找定义）
- `_resolve_template()` — 第 5742 行调用（需要查找定义）

**数据库表：**
- `workflows` — 工作流主表
- `workflow_steps` — 步骤状态
- `workflow_recovery_operations` — 恢复操作记录
- `workflow_step_attempts` — 步骤执行尝试记录

---

## 预防措施

1. **路径规范：** 所有文件操作必须使用绝对路径或明确相对于 `workspace` 的路径
2. **日志增强：** 在 `run_workflow()` 初始化阶段增加详细日志，记录每个文件操作
3. **异常处理：** FileNotFoundError 应该包含完整的绝对路径，便于诊断
4. **测试用例：** 添加竞赛工作流的自动化测试，覆盖带有中文文件名的场景

---

## 诊断工具

使用以下 Python 脚本快速诊断类似问题：

```python
import sqlite3, json, os

db_path = 'runtime/backend/vibe.db'
wf_id = input("输入工作流 ID: ")

conn = sqlite3.connect(db_path)
conn.row_factory = sqlite3.Row

# 检查工作流状态
wf = dict(conn.execute('SELECT * FROM workflows WHERE id=?', (wf_id,)).fetchone())
print(f"\n工作流: {wf['title']}")
print(f"状态: {wf['status']}, 当前步骤: {wf['current_step']}")
print(f"工作区: {wf['workspace_dir']}")

# 检查步骤状态
print("\n步骤状态:")
for row in conn.execute('SELECT skill_name, status, error_message FROM workflow_steps WHERE workflow_id=? ORDER BY step_order', (wf_id,)):
    print(f"  {row['skill_name']:<25} {row['status']:<15} {str(row['error_message'] or '')[:60]}")

# 检查最近恢复操作
print("\n最近恢复操作:")
for row in conn.execute('SELECT created_at, status, error_message FROM workflow_recovery_operations WHERE workflow_id=? ORDER BY created_at DESC LIMIT 3', (wf_id,)):
    print(f"  {row['created_at'][:19]} {row['status']:<10} {str(row['error_message'] or '')[:80]}")

# 检查工作区文件
print("\n工作区文件检查:")
user_data = os.path.join(wf['workspace_dir'], 'user_data')
if os.path.isdir(user_data):
    files = [f for f in os.listdir(user_data) if not f.startswith('_')]
    print(f"  user_data/ 包含 {len(files)} 个文件: {files[:10]}")
else:
    print("  user_data/ 不存在!")

conn.close()
```

---

**诊断结论：** 工作流恢复失败的直接原因是文件路径处理 bug（相对路径 vs 绝对路径），而非网络问题。"fail to fetch" 可能是用户对错误的描述，或后端在其他请求中崩溃。修复路径处理逻辑即可解决。

# G0 可信验收修复实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）逐任务实现此计划。步骤使用复选框（`- [ ]`）语法跟踪进度。

**目标：** 在不改变根合同、冻结 lock、质量阈值和 G1 产品行为的前提下，让 G0 的 12 个 tamper vector 全部走真实 checker，并由受保护快照、恢复演练、supervisor receipt、独立复核和权威 journal 形成可接受的 G0 工程门。

**架构：** 新增两个无副作用的 focused checker，分别验证 task allowlist 的 pre/post tree 差异和逐来源 license decision。`bootstrap_contract.py` 只编排真实 mutation 并记录 checker receipt；`g0_runner.py` 从 OS 根哈希、checker、恢复、测试 lane 等原始 receipt 推导报告。冻结的 `phase-contract.lock`、外部 `开发指导.bootstrap.json` 与 `verify_truth.py` 保持逐字节不变。

**技术栈：** Python 3、pytest、SHA-256 canonical JSON、Windows ACL/icacls、Git plumbing、现有 ProcessSupervisor 与 hash-chained journal。

---

## 冻结边界与文件职责

- 不修改：`D:\科研软件制作\开发指导.bootstrap.json`
- 不修改：`开发指导.md`
- 不修改：`harness/phase-contract.lock`
- 不修改：`harness/scripts/verify_truth.py`
- 创建：`harness/scripts/task_boundary.py` — 解析 allowlist、计算 pre/post 变化、拒绝越界路径。
- 创建：`harness/scripts/source_provenance.py` — 验证逐来源许可证 decision receipt 及 reuse mode。
- 修改：`harness/scripts/bootstrap_contract.py:224-283` — TV-011/012 调用真实 checker 并返回 checker receipt。
- 修改：`harness/scripts/g0_runner.py:380-483` — 捕获 OS hash receipt、tamper 细节和 acceptance 前置，不自行提升状态。
- 修改：`tests/test_harness_g0.py:31-50` — 增加真实 mutation、checker receipt 与禁止硬编码测试。
- 创建：`harness/adjudications/G0-independent-review.json` — 由独立只读 reviewer 写入的结构化裁决；实现者不得生成 accepted verdict。
- 生成：`harness/evidence/G0/*` — trusted runner 的命令、输入、输出、checker、恢复、ACL、JUnit 与 gate report。
- 修改：`harness/events.jsonl`、`harness/state.json` — 仅在独立复核接受且所有 G0 门 PASS 后追加 acceptance event 并重建投影。

所有实现文件在编辑前记录 SHA256；新文件记录 `absent_at_g0_repair_start`。只精确 stage 本任务路径；不得使用 `git add -A`、`git commit -a`、stash、reset、clean、pull、merge、rebase 或 checkout 旧提交。

### 任务 1：锁定不可变输入与前序 ownership

**文件：**
- 生成：`harness/evidence/G0/repair-preflight.json`
- 生成：`harness/baseline/g0-repair-ownership.json`

- [ ] **步骤 1：用 OS 工具重新核验根合同**

运行：

```powershell
Get-FileHash -Algorithm SHA256 -LiteralPath 'D:\科研软件制作\开发指导.bootstrap.json' | ConvertTo-Json -Compress
```

预期：退出码 0，Hash 为 `A843E10612A602E8226CFC89F5976811E4E0094B41DFA5F60F65DFD5DB51CDF8`。

- [ ] **步骤 2：记录四个冻结输入的 before hash**

运行：

```powershell
Get-FileHash -Algorithm SHA256 -LiteralPath @(
  'D:\科研软件制作\开发指导.bootstrap.json',
  'D:\科研软件制作\Vibe-research源码\开发指导.md',
  'D:\科研软件制作\Vibe-research源码\harness\phase-contract.lock',
  'D:\科研软件制作\Vibe-research源码\harness\scripts\verify_truth.py'
) | ConvertTo-Json -Compress
```

预期：退出码 0；receipt 包含四项非空 SHA256。

- [ ] **步骤 3：捕获当前 Git/index/refs/status 与实现文件 before hash**

运行：

```bash
git -C "D:/科研软件制作/Vibe-research源码" rev-parse HEAD
git -C "D:/科研软件制作/Vibe-research源码" for-each-ref --format='%(refname) %(objectname)'
git -C "D:/科研软件制作/Vibe-research源码" diff --cached --name-status
git -C "D:/科研软件制作/Vibe-research源码" status --porcelain=v2 --branch --untracked-files=all
```

预期：退出码均为 0；不得改变 index；所有当前变化归类为 `preexisting_user_or_previous`，本计划随后产生的路径归类为 `agent_g0_repair`。

- [ ] **步骤 4：验证受保护快照和恢复 receipt**

运行：

```bash
python -B harness/scripts/restore_drill.py \
  --baseline "D:/科研软件制作/Vibe-research源码-G0Protected-20260717" \
  --output "D:/科研软件制作/Vibe-research-G0-protected-restore-receipt-20260717-rerun.json"
```

预期：退出码 0；`verdict=PASS`、`manifest_entries_verified=4504`、`manifest_bytes_verified=383368530`，HEAD/index/refs/status 与 deletion markers 全部匹配。

### 任务 2：以 TDD 实现 allowed-path checker

**文件：**
- 创建：`harness/scripts/task_boundary.py`
- 修改：`tests/test_harness_g0.py`

- [ ] **步骤 1：编写失败测试**

在 `tests/test_harness_g0.py` 增加：

```python
from task_boundary import evaluate_allowed_paths


def test_allowed_path_checker_fails_on_real_out_of_scope_change() -> None:
    result = evaluate_allowed_paths(
        before={"harness/evidence/G0/a.json": "a", "backend/main.py": "b"},
        after={"harness/evidence/G0/a.json": "c", "backend/main.py": "d"},
        allowed_paths=["harness/**"],
    )
    assert result["verdict"] == "FAIL"
    assert result["changed_paths"] == [
        "backend/main.py",
        "harness/evidence/G0/a.json",
    ]
    assert result["violations"] == ["backend/main.py"]
    assert result["denominator"] == 2


def test_allowed_path_checker_passes_only_in_scope_changes() -> None:
    result = evaluate_allowed_paths(
        before={"harness/a.json": "a"},
        after={"harness/a.json": "b", "harness/new.json": "c"},
        allowed_paths=["harness/**"],
    )
    assert result == {
        "verdict": "PASS",
        "changed_paths": ["harness/a.json", "harness/new.json"],
        "violations": [],
        "numerator": 2,
        "denominator": 2,
    }
```

- [ ] **步骤 2：运行测试确认 RED**

运行：

```bash
python -B -m pytest -p no:cacheprovider tests/test_harness_g0.py::test_allowed_path_checker_fails_on_real_out_of_scope_change tests/test_harness_g0.py::test_allowed_path_checker_passes_only_in_scope_changes -q
```

预期：FAIL，原因是 `task_boundary` 或 `evaluate_allowed_paths` 不存在。

- [ ] **步骤 3：实现最小 checker**

`harness/scripts/task_boundary.py` 定义：

```python
from __future__ import annotations

import fnmatch
from typing import Mapping, Sequence


def _matches(path: str, pattern: str) -> bool:
    if pattern.endswith("/**"):
        prefix = pattern[:-3].rstrip("/")
        return path == prefix or path.startswith(prefix + "/")
    return fnmatch.fnmatchcase(path, pattern)


def evaluate_allowed_paths(
    *,
    before: Mapping[str, str | None],
    after: Mapping[str, str | None],
    allowed_paths: Sequence[str],
) -> dict[str, object]:
    changed = sorted(
        path for path in set(before) | set(after)
        if before.get(path) != after.get(path)
    )
    violations = [
        path for path in changed
        if not any(_matches(path, pattern) for pattern in allowed_paths)
    ]
    return {
        "verdict": "FAIL" if violations else "PASS",
        "changed_paths": changed,
        "violations": violations,
        "numerator": len(changed) - len(violations),
        "denominator": len(changed),
    }
```

- [ ] **步骤 4：运行测试确认 GREEN**

重复步骤 2 命令。预期：2 passed。

### 任务 3：以 TDD 实现 source-provenance checker

**文件：**
- 创建：`harness/scripts/source_provenance.py`
- 修改：`tests/test_harness_g0.py`

- [ ] **步骤 1：编写失败测试**

增加：

```python
from source_provenance import evaluate_source_provenance


def test_source_provenance_blocks_missing_receipt() -> None:
    result = evaluate_source_provenance([
        {
            "source": "repo/file.py@abc",
            "license_expression": "MIT",
            "reuse_mode": "direct_reuse",
            "license_decision_receipt": None,
            "obligations": [],
            "resolved_obligations": [],
        }
    ])
    assert result["verdict"] == "BLOCKED"
    assert result["reasons"] == ["missing_license_decision_receipt:repo/file.py@abc"]


def test_source_provenance_blocks_incompatible_direct_reuse() -> None:
    result = evaluate_source_provenance([
        {
            "source": "repo/file.py@abc",
            "license_expression": "UNKNOWN",
            "reuse_mode": "direct_reuse",
            "license_decision_receipt": "receipt.json",
            "obligations": [],
            "resolved_obligations": [],
        }
    ])
    assert result["verdict"] == "BLOCKED"
    assert result["reasons"] == ["incompatible_direct_reuse:repo/file.py@abc:UNKNOWN"]


def test_source_provenance_accepts_compatible_resolved_source() -> None:
    result = evaluate_source_provenance([
        {
            "source": "repo/file.py@abc",
            "license_expression": "Apache-2.0",
            "reuse_mode": "direct_reuse",
            "license_decision_receipt": "receipt.json",
            "obligations": ["NOTICE"],
            "resolved_obligations": ["NOTICE"],
        }
    ])
    assert result["verdict"] == "PASS"
    assert result["denominator"] == 1
```

- [ ] **步骤 2：运行测试确认 RED**

运行：

```bash
python -B -m pytest -p no:cacheprovider tests/test_harness_g0.py::test_source_provenance_blocks_missing_receipt tests/test_harness_g0.py::test_source_provenance_blocks_incompatible_direct_reuse tests/test_harness_g0.py::test_source_provenance_accepts_compatible_resolved_source -q
```

预期：FAIL，原因是模块或函数不存在。

- [ ] **步骤 3：实现最小 checker**

`source_provenance.py` 定义兼容直接复用集合 `{MIT, Apache-2.0, CC0-1.0}`；任何缺 receipt、UNKNOWN/NC/ShareAlike/copyleft/不兼容直接复用、或 `obligations - resolved_obligations` 非空均返回 `BLOCKED`。空 sources 返回 `INVALID`，不能以空集通过。返回字段固定为 `verdict`、`reasons`、`numerator`、`denominator`。

- [ ] **步骤 4：运行测试确认 GREEN**

重复步骤 2 命令。预期：3 passed。

### 任务 4：让 TV-011/012 真实调用 checker

**文件：**
- 修改：`harness/scripts/bootstrap_contract.py:224-283`
- 修改：`tests/test_harness_g0.py`

- [ ] **步骤 1：编写失败测试，禁止硬编码 tamper verdict**

增加：

```python
def test_tv_011_and_tv_012_include_real_checker_receipts() -> None:
    contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
    lock = json.loads(LOCK.read_text(encoding="utf-8"))
    result = run_tamper_vectors(contract, lock)
    by_id = {case["id"]: case for case in result["cases"]}
    assert by_id["TV-011"]["checker"]["name"] == "evaluate_allowed_paths"
    assert by_id["TV-011"]["checker"]["input_sha256"]
    assert by_id["TV-011"]["actual"] == "FAIL"
    assert by_id["TV-012"]["checker"]["name"] == "evaluate_source_provenance"
    assert by_id["TV-012"]["checker"]["input_sha256"]
    assert by_id["TV-012"]["actual"] == "BLOCKED"
```

另加源码合同测试：

```python
def test_tamper_runner_does_not_assign_tv_011_or_tv_012_expected_verdict() -> None:
    source = (SCRIPTS / "bootstrap_contract.py").read_text(encoding="utf-8")
    assert 'outcomes["TV-011"] = "FAIL"' not in source
    assert 'outcomes["TV-012"] = "BLOCKED"' not in source
```

- [ ] **步骤 2：运行测试确认 RED**

运行：

```bash
python -B -m pytest -p no:cacheprovider tests/test_harness_g0.py::test_tv_011_and_tv_012_include_real_checker_receipts tests/test_harness_g0.py::test_tamper_runner_does_not_assign_tv_011_or_tv_012_expected_verdict -q
```

预期：FAIL，现有 cases 无 checker 且源码含硬编码 assignments。

- [ ] **步骤 3：替换硬编码实现**

在 `run_tamper_vectors` 内：

```python
boundary_input = {
    "before": {"harness/evidence/G0/inside.json": "a", "backend/main.py": "b"},
    "after": {"harness/evidence/G0/inside.json": "c", "backend/main.py": "d"},
    "allowed_paths": ["harness/**"],
}
boundary = evaluate_allowed_paths(**boundary_input)

provenance_input = [{
    "source": "isolated/source.py@tampered",
    "license_expression": "UNKNOWN",
    "reuse_mode": "direct_reuse",
    "license_decision_receipt": None,
    "obligations": [],
    "resolved_obligations": [],
}]
provenance = evaluate_source_provenance(provenance_input)
```

将 `outcomes` 从字符串改为包含 `actual` 与 `checker` 的记录；TV-001 至 TV-010 也由原实际 validator 结果包装为记录。checker receipt 至少含函数名、checker 文件 SHA256、canonical input SHA256 和非空 denominator。

- [ ] **步骤 4：运行 targeted 与全部 tamper 测试**

运行：

```bash
python -B -m pytest -p no:cacheprovider tests/test_harness_g0.py::test_tv_011_and_tv_012_include_real_checker_receipts tests/test_harness_g0.py::test_tamper_runner_does_not_assign_tv_011_or_tv_012_expected_verdict tests/test_harness_g0.py::test_all_bootstrap_tamper_vectors_reject_the_mutation -q
```

预期：3 passed；tamper summary 为 12/12 PASS，而 TV-011 actual=FAIL、TV-012 actual=BLOCKED。

### 任务 5：强化 trusted G0 runner，不越权提升状态

**文件：**
- 修改：`harness/scripts/g0_runner.py:380-483`
- 修改：`tests/test_harness_g0.py`

- [ ] **步骤 1：为 OS hash receipt 和 acceptance 前置写失败测试**

测试要求：root receipt 含 `tool=Get-FileHash`、argv、exit code、expected/actual；tamper receipt 含 12 个真实 case；gate report 在缺独立 adjudication 时为 `BLOCKED`；runner 不直接调用 `append_event(... accepted ...)`。

- [ ] **步骤 2：运行 targeted 测试确认 RED**

运行：

```bash
python -B -m pytest -p no:cacheprovider tests/test_harness_g0.py -k "os_hash_receipt or independent_adjudication or runner_does_not_self_accept" -q
```

预期：FAIL，现有 runner 仅用 Python hash 且可直接生成总体 report。

- [ ] **步骤 3：实现 supervisor receipt**

新增 runner 内部函数执行：

```powershell
Get-FileHash -Algorithm SHA256 -LiteralPath D:\科研软件制作\开发指导.bootstrap.json
```

receipt 必须保存 argv、cwd、started/finished UTC、exit code、stdout/stderr SHA256、expected/actual hash。OS 命令失败或 hash 不匹配时总体 `BLOCKED`。

- [ ] **步骤 4：实现独立 adjudication 前置**

`g0_runner.py` 只在 `harness/adjudications/G0-independent-review.json` 存在、schema 合法、`verdict=accepted`、reviewer 输入 hash 与当前 artifact manifest 一致时允许 gate report 为 PASS；否则为 BLOCKED。runner 只生成 report，不写正式 acceptance event。

- [ ] **步骤 5：运行 targeted 测试确认 GREEN**

重复步骤 2 命令。预期：全部通过。

### 任务 6：运行 G0 工程验证并生成新鲜 receipts

**文件：**
- 生成：`harness/evidence/G0/commands.jsonl`
- 生成：`harness/evidence/G0/lane-*.xml`
- 生成：`harness/evidence/G0/g0-checks.json`
- 生成：`harness/evidence/G0/artifact-manifest.json`
- 生成：`harness/evidence/G0/g0-gate-report.json`

- [ ] **步骤 1：运行 focused G0 tests**

```bash
"D:/科研软件制作/Vibe-research源码/runtime/python/python.exe" -B -m pytest -p no:cacheprovider tests/test_harness_g0.py -q --junitxml harness/evidence/G0/test-harness-g0.xml
```

预期：退出码 0，无 skip，无 cache 写入。

- [ ] **步骤 2：运行 bootstrap CLI 三联检查**

```bash
python -B harness/scripts/bootstrap_contract.py verify --contract "D:/科研软件制作/开发指导.bootstrap.json" --os-hash a843e10612a602e8226cfc89f5976811e4e0094b41dfa5f60f65dfd5db51cdf8
python -B harness/scripts/bootstrap_contract.py verify-lock --contract "D:/科研软件制作/开发指导.bootstrap.json" --lock harness/phase-contract.lock
python -B harness/scripts/bootstrap_contract.py tamper-test --contract "D:/科研软件制作/开发指导.bootstrap.json" --lock harness/phase-contract.lock
```

预期：三个退出码均为 0；coverage 207/207；tamper 12/12，TV-011/012 带 checker receipt。

- [ ] **步骤 3：运行 supervised 非 live lanes**

```bash
"D:/科研软件制作/Vibe-research源码/runtime/python/python.exe" -B harness/scripts/g0_runner.py
```

预期：若尚无独立 adjudication，工程 checks 可以 PASS，但最终 report 必须 BLOCKED；任何 lane FAIL 均保持 FAIL/BLOCKED，不原样重试。

- [ ] **步骤 4：验证冻结文件未变化**

重新执行任务 1 步骤 2。预期：四个 SHA256 与 preflight 完全一致。

- [ ] **步骤 5：验证 index 未被污染及 allowed paths**

```bash
git -C "D:/科研软件制作/Vibe-research源码" diff --cached --name-status
git -C "D:/科研软件制作/Vibe-research源码" status --porcelain=v2 --branch --untracked-files=all
```

预期：index 与 preflight 一致；本任务新增/修改仅在 ADR-G0-002 的 allowed implementation scope 内。

### 任务 7：独立只读复核与正式 journal 接受

**文件：**
- 创建：`harness/adjudications/G0-independent-review.json`
- 修改：`harness/events.jsonl`
- 修改：`harness/state.json`

- [ ] **步骤 1：启动全新只读 reviewer**

reviewer 必须冷读：实现 diff、两 checker 源码、12 个 tamper case、OS hash receipt、ACL/write-probe receipt、恢复 receipt、ownership、secret scan、journal fault matrix、所有 lane JUnit、artifact manifest 与冻结文件 hash。其结构化裁决包含 actor/session/model、权限、prompt hash、每个输入 SHA256、findings、verdict。

- [ ] **步骤 2：若 reviewer 提出 finding，记录并修复**

每个 finding 写入 `harness/findings.jsonl`，修复后重新运行受影响测试与全部 G0 runner；输入/输出/失败签名不变时不得原样重试。

- [ ] **步骤 3：重新执行 OS hash 后生成最终 gate report**

预期：只有独立 adjudication 的 input hash 与当前 artifact manifest 一致，且所有 required checks PASS，trusted runner 才生成 PASS。

- [ ] **步骤 4：使用 journal CLI 追加 acceptance event**

```bash
python -B harness/scripts/journal.py append \
  --journal harness/events.jsonl \
  --state harness/state.json \
  --type phase_state \
  --payload '{"phase_id":"G0","state":"accepted","assurance_class":"engineering_assurance","gate_report":"harness/evidence/G0/g0-gate-report.json"}' \
  --idempotency-key 'G0:engineering-accepted:<gate-report-sha256>'
python -B harness/scripts/journal.py verify --journal harness/events.jsonl --state harness/state.json
```

预期：两个退出码均为 0；state 从 journal 可重建，G0 为 accepted；重复 idempotency key 必须失败。

- [ ] **步骤 5：精确 stage 和 commit 本任务文件**

先逐项核对 staged 内容，再运行：

```bash
git add \
  harness/scripts/task_boundary.py \
  harness/scripts/source_provenance.py \
  harness/scripts/bootstrap_contract.py \
  harness/scripts/g0_runner.py \
  tests/test_harness_g0.py \
  harness/decisions/ADR-G0-002-trusted-bootstrap-acceptance.md \
  harness/decisions/2026-07-17-g0-trusted-acceptance-plan.md \
  harness/adjudications/G0-independent-review.json \
  harness/events.jsonl \
  harness/state.json
git diff --cached --check
git diff --cached --name-status
git commit -m "fix: establish trusted G0 acceptance"
```

预期：只包含列出的 G0-owned 文件；不得包含任何前序 backend/frontend/release/skills 变化或秘密。若 hooks 失败，修复根因，不使用 `--no-verify`。

## 自检结论

- 规格覆盖：真实 TV-011/012、OS hash、冻结 lock/runner、ACL、恢复、ownership、receipt、独立 reviewer、journal/state 全部有对应任务。
- 范围：仅 G0；未触碰 G1 行为。
- 非空与失败语义：allowed-path 无变化不可用于 TV-011；source provenance 空集为 INVALID；缺 receipt/不兼容均 BLOCKED。
- 类型一致：checker 返回结构固定；tamper cases 的 `actual` 从 checker/validator 返回，不从 expected 复制。
- 禁止占位：所有实现步骤、命令、预期状态和文件路径均明确。

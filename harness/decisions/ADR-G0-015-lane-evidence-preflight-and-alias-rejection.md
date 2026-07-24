# ADR-G0-015：Lane 证据目录预检与 JUnit 别名拒绝

- **状态：** 已实施；仅限本地验证，待独立冷读复核。
- **日期：** 2026-07-18
- **范围：** `harness/scripts/g0_runner.py` 与 `tests/test_harness_g0.py`。

## 背景

独立冷读提出两个仍可复现的 G0 证据完整性缺口：

1. `run_lanes` 在验证 `evidence_dir` 位于 workspace 内之前，已经创建 supervisor，并允许 lane 写入 JUnit、stdout 与 stderr；工作区外目录可在随后 receipt 验证失败前留下写入物。
2. 规范文件名 `lane-<lane>.xml` 的 NTFS 硬链接通过了路径与 SHA-256 检查。它的名称和内容哈希正确，但其字节身份仍可由另一条目录项共享，不能作为独占的 raw evidence 身份。

红测在系统临时目录执行。第一次将硬链接直接建在先前外部写入试验已经生成的目标上，得到 `WinError 183`；未修改产品 workspace。第二次改用独立 `alias-evidence` 目录，确认当前实现同时存在“外部目录先写入”和“硬链接被 PASS 接受”两项缺口。该红测不是 qualification，也不提升任何科学或发布状态。

## 决定

1. `run_lanes` 的第一项动作必须是 `_preflight_lane_evidence_dir`。若证据目录词法路径不在 workspace 内、缺失、不是目录、包含 symlink/reparse component，或解析后离开 workspace，则抛出 `G0Error`；不得构造 supervisor、执行 pytest 或写 stdout/stderr/JUnit。
2. Receipt 验证同时要求：
   - 词法路径与 `evidence_dir/lane-<lane>.xml` 完全一致（按 Windows 大小写归一）；
   - 解析路径仍在证据目录内；
   - JUnit 不是 symlink/reparse point；
   - `lstat().st_nlink == 1`，拒绝硬链接；
   - `junit_exists`、格式正确的 SHA-256、实际文件和 digest 一致。
3. 运行时预检与事后 receipt 验证使用同一目录边界规则；任何错误均 fail-closed，不能转换为 `PASS` 或降级为普通 warning。

## 验证要求

- 单元测试以真实 NTFS hard link 验证 `junit_hardlink_not_allowed`。
- 单元测试以受控 supervisor 检查，确认外部 evidence 路径会在 supervisor 调用和任何输出文件之前抛出 `G0Error`。
- 该变更必须通过全量 `tests/test_harness_g0.py`、受影响 unit lane、当前 lane summary 的严格复验及新的独立冷读。

## 后果与未决项

这只修复本地工程完整性；不接受 G0，也不解除 `F003`、`F004`、`F006` 或 `F007`。特别是，真实 Claude Code 未登录、Codex 429、受保护 ownership attestation 和独立 phase-contract handoff 仍需外部信任边界中的新证据。

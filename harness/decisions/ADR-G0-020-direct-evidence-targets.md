# ADR-G0-020：lane evidence 只允许 evidence 根目录下的直系目标

- **状态：** 已实施；仅限本地工程验证，待独立冷读。
- **日期：** 2026-07-18
- **范围：** `_commit_staged_evidence_file` 与 lane evidence target path contract。

## 背景

第三轮独立冷读发现，通用 helper 仅检查目标 leaf，允许 `evidence/child/report.xml` 这一词法上在 evidence 内的路径。当 `child` 是一个指向工作区外的真实 Windows junction 且外部 leaf 尚不存在时，旧代码会把 staged 文件复制到外部目录并返回成功。

真实红测复现：evidence 根目录不是 reparse point，`child` 是真实 junction，`_commit_staged_evidence_file(staged, evidence/child/report.xml, guard)` 返回成功且在外部创建文件。

## 决定

lane runner 的生产 contract 只产生固定的直系文件：

- `lane-<lane>.xml`
- `lane-<lane>.stdout.txt`
- `lane-<lane>.stderr.txt`

因此 commit helper 现在要求 `target.parent` 的规范化绝对路径**严格等于**已验证的 `guard.raw`。任何 descendant path 都以 `evidence_target_parent_not_canonical` fail-closed 拒绝。随后仍执行 leaf 的无条件 `lstat` reparse/non-regular/hardlink 检查及目录 identity guard。

## 验证

新增真实 Windows junction test：在 evidence 中创建 `child` junction，尝试 commit staged XML 到 `child/report.xml`，必须在 copy 前抛错且外部目录为空。

## 范围限制

该决定故意收窄通用 helper，以匹配本产品 lane evidence 的固定 flat namespace。它不把本地路径检查声称为内核级原子封印；但消除了已经可复现的、稳定 descendant reparse component 绕过。

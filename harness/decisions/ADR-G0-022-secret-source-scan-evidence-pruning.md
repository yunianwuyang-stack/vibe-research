# ADR-G0-022: 将 source secret-scan corpus 与可复核 evidence artifacts 分离

- **状态：** 已实施本地回归修复；不构成 G0、release 或外部验收接受
- **日期：** 2026-07-18
- **范围：** `G0-F-009`、`tests/test_surface_parity_lifecycle.py`

## 背景

`test_secret_scan_source_has_no_hardcoded_test_keys` 的目的在于扫描源代码中的硬编码测试凭据。它以前使用 `ROOT.rglob("*")` 遍历整个工作树。G0 的历史红证据有意保留了一个 dangling NTFS junction，以证明 destination reparse 防护。在 bundled CPython runtime 中，`Path.rglob()` 会尝试下降到该 junction，并在扫描 source 之前抛出 `FileNotFoundError`。

该行为在仓库外只读 baseline copy 上、使用实际 unit lane 的 bundled runtime 重现。不得删除或修改该 dangling artifact，因为它是既有安全 red characterization 的一部分。

## 决策

1. secret-source 测试的显式语料定义为产品与测试源文件，**不包含** `harness/evidence`；该目录保存验收、红测和历史 provenance，而不是产品 source corpus。
2. 使用 top-down `os.walk(..., followlinks=False)`，并在进入 `harness/evidence` 前进行明确 prune。
3. 扫描器保持 fail-closed：除上述唯一 evidence exclusion 之外，任何 reparse directory/file 或不可读取 source entry 都被收集并以断言失败报告；不静默跳过。
4. 保留原有三类凭据 pattern、文件扩展名范围与 `assert not hits`；新增非空 `scanned_source_files` denominator 断言。

## 后果与边界

- 历史 dangling junction 被完整保留，source secret test 可完成其定义的 source corpus 检查。
- 该决策不缩小产品 source scan 的范围，也不改变实际 `secret_scan` 实现或发布安全标准。
- F009 仅解除本地 unit regression 的 traversal blocker；F003/F004/F006/F007、external validation、人类/专家与 sealed evaluation blocker 仍保持原状态，G0 仍为 `BLOCKED`。
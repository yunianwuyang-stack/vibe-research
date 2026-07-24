# ADR-G0-016：不可变 receipt 聚合校正

- **状态：** 已实施；仅限本地证据解释，待独立冷读。
- **日期：** 2026-07-18
- **范围：** G0-P1 的 verification aggregation artifact；不修改任何原始 command receipt、stdout、stderr 或产品代码。

## 发现

`g0-p1-preflight-alias-verify-20260718T111601Z/verification-summary.json` 的临时写入器出现两项聚合错误：

1. 它声明的 strata 含 `root_contract`、两条测试和五条 lane，却将 denominator 写成 7、numerator 写成 4。
2. unit stdout 的 warning parser 取得首次出现的 `11 warnings`，而终端 pytest 汇总是 `25 warnings`。

这些错误不改变 root hash、supervisor command receipt、stdout/stderr 的字节或测试的退出码，但使旧 aggregate 不能用作合格 qualification evidence。

## 决定

- 保留旧 run directory 原样，不覆写、不删除、不改变其 hashes。
- 使用其 receipt 中记录的 stdout SHA-256 复核原始文件，并以独立、fail-closed 的派生 artifact 报告终端计数。
- 新 aggregate 必须包含八个非空 strata：root contract、harness test、unit lane、unit/contract/integration/desktop/release JUnit receipt；deterministic gate 的 CI 明示为 `NOT_APPLICABLE`，不得伪造抽样 CI。
- 校正后仍只代表 local verification，不解除任何外部或人工验证阻断。

## 后果

任何后续 reviewer 只能引用 `receipt-aggregation-correction.json` 的 8/8 aggregate，且必须同时检查其 source receipt hashes。旧 `verification-summary.json` 标记为 superseded，不得作为 gate acceptance 输入。

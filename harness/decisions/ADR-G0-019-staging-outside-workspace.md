# ADR-G0-019：lane staging 必须位于 workspace 外

- **状态：** 已实施；仅限本地工程验证，待独立冷读。
- **日期：** 2026-07-18
- **范围：** `run_lanes` 临时 staging 位置与真实 unit-lane E2E evidence。

## 发现

真实 `ProcessSupervisor` + real pytest unit-lane E2E 在 2026-07-18T12:09:16Z 运行。unit lane 通过 316 个测试、canonical receipt 验证通过，但 wrapper 故意把 `TEMP/TMP` 设在 evidence run directory 内。`TemporaryDirectory` 因而创建了一个位于 evidence 树内的 staging 文件，child 的 `--junitxml` 参数也落在该树内。

这不是测试成功：它说明 staging 与 final evidence 名称不同，却没有满足“child 不应直接持有 workspace evidence 路径”的边界。该历史 run 保留为 fail-closed 红测，不得作为 PASS receipt。

## 决定

1. `run_lanes` 创建 staging directory 后、构造 `ProcessSupervisor` 前，必须验证 staging 的 lexical 和 resolved 路径均在 workspace 外，且 staging 不是 reparse point。
2. 若 `TMP/TEMP` 或等效环境把 staging 指向 workspace，抛出 `G0Error("lane_staging_inside_workspace_not_allowed")`；不得构造 supervisor、启动 child 或写 evidence。
3. formal verifier 的 controlled TMP/TEMP 必须位于 workspace 外；pytest `--basetemp` 可由 receipt-visible受控目录指定，但需单独证明其路径和卷。

## 后果

- 旧 `g0-p1-real-staging-unit-e2e-20260718T120916Z` 的 wrapper FAIL 是正确且不可覆盖的历史证据。
- 一个新的真实 E2E 必须使用 workspace 外 staging，通过后才能作为本轮本地 E2E evidence。
- 该修复不承诺内核级绝对原子封印，也不解除任何 G0 外部、人工、凭据或 sealed-eval blocker。

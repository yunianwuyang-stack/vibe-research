# ADR-G0-017：证据目录身份守卫与子进程 staging

- **状态：** 已实施；只完成本地工程验证，待独立冷读。
- **日期：** 2026-07-18
- **范围：** `harness/scripts/g0_runner.py` 与 `tests/test_harness_g0.py`。

## 背景

独立冷读指出，原有预检只验证一次路径。真实 Windows junction 红测证明：在 `ProcessSupervisor` 构造时把原本正常的 evidence directory 替换成指向工作区外的 junction，旧 `run_lanes` 会把 `--junitxml` 交给该外部目录，并在事后 receipt validation 失败前写出 JUnit、stdout 和 stderr。

## 决定

1. 建立 `_EvidenceDirectoryGuard`，在预检后保存 evidence directory 的 lexical path、resolved path 与 `lstat` identity；在 supervisor 构造后、每个 lane 启动前、子进程返回后、以及每个 evidence 文件提交前后重新检查。路径变为 reparse、逃离 workspace 或 identity 改变时立即抛出 `G0Error`。
2. pytest 的 `--junitxml` 改为每次运行创建的、由 harness 拥有的临时 staging 文件；stdout/stderr 也先在 staging 生成。只有 guard 保持有效时才复制到 canonical workspace evidence path。
3. 提交前后拒绝已有的 reparse、hardlink 或非普通 evidence target，避免覆盖外部别名。
4. 真实 Windows junction 测试覆盖：初始 reparse 路径、supervisor 构造后的替换、以及子进程运行期间替换；这些场景必须无外部文件、或在启动前无 supervisor 调用。

## 安全与范围

Windows 可变名称空间无法由普通 pathlib API 提供内核级、永久原子封印。本 ADR 不把本地 guard 宣称为对特权并发攻击者的绝对隔离；它将旧的可利用窗口缩小为可检测的提交边界，并使子进程不再直接持有 workspace evidence 路径。任何检测到的身份变化均阻断 lane 和 G0。受保护 ACL、独立执行主机或内核级 handle-relative writer 属于外部 trust/runner 资格范围，不能由此本地修复伪造。

## 验证

- 原实现红测：真实 junction 产生三份外部文件后才 FAIL。
- 新测试：外部路径和初始 junction 在 supervisor 构造前被拒绝；构造期间或运行期间的替换不启动/不提交 workspace evidence，且外部目录保持为空。
- 必须通过完整 harness 测试和受影响 full unit lane，再交由独立冷读复核。

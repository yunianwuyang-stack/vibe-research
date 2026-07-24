# ADR-G0-018：悬空重解析目标与实际临时目录来源绑定

- **状态：** 已实施；仅限本地工程验证，待独立冷读。
- **日期：** 2026-07-18
- **范围：** lane evidence commit precondition 与 G0-P1 临时目录 provenance receipt。

## 背景

第二轮独立冷读发现两项具体缺口：

1. `_assert_safe_evidence_target()` 以 `Path.exists()` 判断目标是否存在。Windows 的悬空 junction/symlink 可以 `exists()==False`，但 `lstat()` 仍表明它是 reparse point；若随后 `copyfile()` 跟随该对象，可能在事后检测前写入外部目标。
2. 先前 `temporary_volume_ntfs` 只查询固定 `C:`，没有绑定实际 pytest `tmp_path` 或 `TemporaryDirectory` staging parent。

真实红测先创建受控目标与 junction，再删除该受控目标，得到 `exists()==False` 且 `st_file_attributes` 含 reparse flag 的对象；旧 guard 返回而不报错。

## 决定

1. evidence target 的检查无条件调用 `lstat()`：仅 `FileNotFoundError` 表示目标不存在。任何可 `lstat()` 的 reparse、非普通文件或 hardlink 都在 `copyfile()` 前被拒绝。
2. 新的 formal verifier 必须为 pytest 明确设置 `TMP`、`TEMP` 和 `--basetemp` 到写入 receipt 的受控实际路径；同一环境中的 Python `tempfile.gettempdir()` 输出和该路径所在卷的 filesystem 由 supervisor receipt 绑定。
3. 旧的固定盘符 NTFS strata 仅保留为历史上下文；新的 provenance-bound receipt 才能作为本地临时目录环境证据。

## 范围限制

本 ADR 关闭已存在悬空 reparse target 的非竞争式绕过，并继续在 commit 前后验证目录身份。它不把 pathlib/copyfile 协议误称为对高权限并发名称空间攻击的内核级原子封印；检测到任意目录身份漂移仍须阻断。

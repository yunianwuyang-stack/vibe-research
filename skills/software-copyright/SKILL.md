---
name: software-copyright
description: "Create evidence-based Chinese software-copyright application materials from the current workspace."
argument-hint: [software-name-and-purpose]
allowed-tools: Bash(*), Read, Write, Edit, Grep, Glob
---

# 软件著作权材料

为当前项目整理软件著作权申请材料：**$ARGUMENTS**

## 输入核验

扫描 `user_data/` 和当前工作区中的代码、界面截图、README、配置与已有说明。只描述实际存在且可定位的功能；缺失信息列入清单，不得猜测版本、完成日期、代码行数或开发者身份。

## 必须输出

- `software-copyright/PRODUCT_OVERVIEW.md`：软件名称建议、用途、技术特点、运行环境、模块清单及对应文件证据。
- `software-copyright/USER_MANUAL.md`：安装、启动、核心操作、异常处理与截图占位清单。
- `software-copyright/SOURCE_CODE_INDEX.md`：建议提交的源程序范围、文件路径、哈希与敏感信息排除项。
- `software-copyright/REGISTRATION_CHECKLIST.md`：仍需申请人确认的主体、日期、版本和材料项。

## 真实性门禁

- 每个功能描述必须附仓库相对路径或截图文件名。
- 不在源代码中出现的功能必须标记为“待实现/待确认”。
- 不输出法律结论，只生成供申请人复核的材料草稿。
- 使用 `Write` 真正创建四个文件。

结束前执行：

```bash
test -s software-copyright/PRODUCT_OVERVIEW.md && test -s software-copyright/USER_MANUAL.md && test -s software-copyright/SOURCE_CODE_INDEX.md && test -s software-copyright/REGISTRATION_CHECKLIST.md
```

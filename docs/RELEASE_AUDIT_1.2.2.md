# Vibe Research 1.2.2 发布审计

## 本次修复

- 修复 Electron 的 loopback 渲染页被后端固定 Origin 拒绝的问题：启动时注入唯一的本地 Origin，后端只接受该 Origin 与每次启动生成的会话令牌。
- 恢复可操作桌面工作台：研究合同、文献检索、34 个工作流模板、执行控制、工作区导出、文件编辑、DOCX 导出、研究运行、审批、环境 Doctor 和 Agent 适配器入口均接入真实 API。
- 产品名称、可执行文件、窗口、托盘、图标、用户数据目录和发布物均统一为 **Vibe Research**。
- 发布包排除历史分析文件；已对打包应用和前端产物执行旧品牌关键字扫描。
- 修复 SecretStore 对任意平台机密材料的 AES-GCM 密钥归一化，避免无效长度导致设置保存失败。

## 验证记录

| 检查 | 结果 |
| --- | --- |
| Python 测试集 | 160 passed |
| 前端 TypeScript typecheck | passed |
| 前端 Vitest | 1 passed |
| 前端 production build | passed |
| Electron EPIPE 回归 | passed |
| 便携版冷启动 | passed：窗口、Vibe 图标和本地后端监听均已确认 |
| 打包应用旧品牌扫描 | passed：无匹配项 |

## 交付物

`../Vibe-research构建版/` 包含：

- `Vibe Research.exe`：无需安装的便携版；
- `Vibe-Research-1.2.2-Setup.exe`：NSIS 安装包；
- `SHA256SUMS.txt`：两份主交付物的 SHA-256；
- `README-安装与使用.md`：安装与启动说明。

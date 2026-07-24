---
name: patent-build
description: >
  读取 patent-draft 产出的 专利交底书/交底书草稿.md，调用 mermaid_render.py 把
  mermaid 围栏渲染成 PNG，再导出 专利交底书/交底书.docx。是"一句话生成专利交底书"
  工作流的第二步（成品阶段）。
user-invocable: false
allowed-tools: >
  Bash, Read, Write, Edit, Glob, Grep
metadata:
  short-description: 渲染图示并导出专利交底书 Word
  stage: build
---

# 专利技术交底书 · 成品阶段（patent-build）

上一步 `patent-draft` 已在 `专利交底书/交底书草稿.md` 写好含 mermaid 围栏的交底书，平台检查点也已让用户确认。本步骤把 mermaid 图渲染为 PNG 并导出 Word。

成品脚本随本明文 skill 一同发布。运行器会注入 `$CLAUDE_SKILL_DIR`，因此脚本目录按
`${PATENT_SCRIPT_DIR:-$CLAUDE_SKILL_DIR/tools}` 解析；`PATENT_SCRIPT_DIR` 仅作为兼容旧版桌面运行时
的覆盖项。目录内包含 `mermaid_render.py`、`md_to_docx.py`、`math_render.py` 与离线
`mermaid.min.js`，不要从网络下载替代脚本。

## 渲染并导出

运行（一条命令完成 mermaid→PNG + 导出 Word）：

```bash
SCRIPT_DIR="${PATENT_SCRIPT_DIR:-$CLAUDE_SKILL_DIR/tools}"
test -f "$SCRIPT_DIR/mermaid_render.py" || { echo "缺少专利成品脚本: $SCRIPT_DIR"; exit 2; }
"${PYTHON:-python}" "$SCRIPT_DIR/mermaid_render.py" \
  -i 专利交底书/交底书草稿.md \
  -o 专利交底书/交底书.md \
  --docx 专利交底书/交底书.docx
```

行为说明：

- 脚本默认先跑 `math_render.py` 渲染 LaTeX 公式，再逐块把 ```mermaid``` 围栏转成 PNG（存到 `专利交底书/mermaid_figures/`、`math_figures/`），保留围栏源码并追加 `<!-- ![图示](...) -->` 注释，最后调用 `md_to_docx.py` 生成 Word。
- **降级不中断**：某个 mermaid 块或 mmdc 渲染失败时，该块保留原围栏文字，其余照常渲染；Word 仍会生成（失败块以代码块形式出现）。Word 导出失败时脚本退出码仍为 0，并在 stderr 给出可手动执行的 `md_to_docx.py` 命令。
- 若 mmdc 完全不可用（无 Node / 无法拉取 mermaid-cli），PNG 无法生成，Word 中 mermaid 以源码文本呈现——这不阻塞流程，但应在汇报里如实说明"系统框图/流程图未渲染成图片"。

## 输出

成功后在 `专利交底书/` 下生成：

- `交底书.md`（图片引用版，保留 mermaid 源码 + 图示注释）
- `交底书.docx`（正式 Word，mermaid 已嵌为 PNG）
- `mermaid_figures/`、`math_figures/`（渲染出的 PNG，可选）

## 完成校验

运行后检查 `专利交底书/交底书.docx` 存在且非空。读一下脚本 stderr：若出现"已写入 Word: ..."即导出成功；若出现"md_to_docx 失败"或渲染警告，按提示重试或如实转达用户。完成后向用户汇报 Word 路径，并说明 mermaid 图是否成功渲染为图片。

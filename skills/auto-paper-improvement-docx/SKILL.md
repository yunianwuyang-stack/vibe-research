---
name: auto-paper-improvement-docx
description: "Word/DOCX 输出的 Markdown 论文改进循环。审稿、修改并复核 Markdown 源文，不调用 LaTeX/PDF。"
argument-hint: [workflow-id]
allowed-tools: Bash(*), Read, Write, Edit, Grep, Glob
---

# DOCX 论文改进循环

本步骤仅服务于 `OUTPUT_FORMAT=docx`。必须改进 Markdown 源文，之后由
`docx-format-check` 与 `docx-export` 生成 Word。

## 输入选择

按顺序选择第一个存在的主文件：

1. `paper/main.md`
2. `HUMANITIES_PAPER.md`
3. `COURSE_PAPER.md`
4. `COURSE_REPORT.md`
5. `NARRATIVE_REPORT.md`

若都不存在，必须失败并明确报告缺少 Markdown 主文，不得用 PDF 代替。

## 执行合同

1. 读取主文、`RESULTS.md`、图表清单与引用。
2. 完成最多 2 轮「审查 → 修改 → 复核」。
3. 只修改可证实的缺陷；不得编造数据、引用或实验结果。
4. 保留 Markdown 图片、表格、公式与章节结构，不得转为 LaTeX。
5. 将修改后的全文回写原主文件。
6. 写入 `paper/PAPER_IMPROVEMENT_LOG.md`，记录每轮问题、修改、证据与复核结论。

## 禁止项

- 禁止查找、编译或验证 `paper/main.tex` / `paper/main.pdf`。
- 禁止运行 `xelatex` / `pdflatex` / `latexmk`。
- 禁止以 PDF 是否存在作为成功条件。

## 完成门禁

```bash
SOURCE=""
for f in paper/main.md HUMANITIES_PAPER.md COURSE_PAPER.md COURSE_REPORT.md NARRATIVE_REPORT.md; do
  [ -f "$f" ] && { SOURCE="$f"; break; }
done
[ -n "$SOURCE" ] || { echo "❌ 缺少 Markdown 主文"; exit 1; }
[ -s "$SOURCE" ] || { echo "❌ Markdown 主文为空"; exit 1; }
[ -s paper/PAPER_IMPROVEMENT_LOG.md ] || { echo "❌ 缺少改进日志"; exit 1; }
echo "✅ DOCX 改进循环完成: $SOURCE"
```


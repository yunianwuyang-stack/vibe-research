#!/usr/bin/env python3
"""检查 MODELING_REPORT.md 中未包围在 $$ 内的裸 LaTeX 命令.

用法:
    python3 _utils/check_latex.py [MODELING_REPORT.md]

退出码:
    0 - 通过
    1 - 发现裸 LaTeX 命令
"""
from __future__ import annotations

import re
import sys
from pathlib import Path


def check(filepath: str = "MODELING_REPORT.md") -> int:
    if not Path(filepath).exists():
        print(f"WARN {filepath} 不存在，跳过检查")
        return 0

    text = Path(filepath).read_text(encoding="utf-8", errors="replace")

    # 0. $$ 必须成对：奇数个 $$ 说明有块级公式没闭合，后面所有内容都会被渲染器吞掉
    n_block = len(re.findall(r"(?<!\\)\$\$", re.sub(r"```.*?```", "", text, flags=re.DOTALL)))
    if n_block % 2 == 1:
        print(f"ERROR $$ 数量为奇数（{n_block}），存在未闭合的块级公式")
        return 1

    # 1. 移除围栏代码块、行内代码、$$ 块、行内 $ 公式（旧版没有去掉 `行内代码`，
    #    SKILL 自带的说明文字里写 `\\begin{aligned}` 也会被误报）
    cleaned = re.sub(r"```.*?```", "", text, flags=re.DOTALL)
    cleaned = re.sub(r"`[^`\n]*`", "", cleaned)
    cleaned = re.sub(r"\$\$[\s\S]*?\$\$", "", cleaned)
    cleaned = re.sub(r"(?<!\\)\$[^\n$]+?(?<!\\)\$", "", cleaned)
    cleaned = re.sub(r"\\\(.*?\\\)", "", cleaned)
    cleaned = re.sub(r"\\\[[\s\S]*?\\\]", "", cleaned)

    # 2. 通用检测：任何 "\字母命令" 在公式外都可疑（旧版只列了 14 个命令，\sum/\alpha/\leq
    #    /\mathbf/\partial/\int 等最常见的全部漏检）。白名单排除 Markdown 里合法的反斜杠用法。
    ALLOW = {"n", "t", "r", "b", "f", "v", "x", "u", "N", "d", "w", "s", "W", "S", "D",
             "newline", "textbackslash", "url", "href", "cite", "ref", "label", "input",
             "include", "usepackage", "documentclass", "section", "subsection", "item"}
    PATTERN = re.compile(r"(?<!\\)\\([a-zA-Z]+)\b")
    bad: list[tuple[int, str]] = []
    for i, line in enumerate(cleaned.split("\n"), 1):
        stripped = line.strip()
        # 跳过 Windows 路径 / 文件路径行
        if re.search(r"[A-Za-z]:\\|\\\\", stripped):
            continue
        cmds = [m.group(1) for m in PATTERN.finditer(line)]
        cmds = [c for c in cmds if c not in ALLOW]
        if cmds:
            shown = ", ".join("\\" + c for c in cmds[:4])
            bad.append((i, "[" + shown + "] " + stripped[:70]))

    if bad:
        print(f"ERROR 发现 {len(bad)} 处裸 LaTeX（缺 $$ 包围）：")
        for ln, s in bad[:10]:
            print(f"  L{ln}: {s}")
        return 1

    print("OK 公式包围检查通过")
    return 0


if __name__ == "__main__":
    fp = sys.argv[1] if len(sys.argv) > 1 else "MODELING_REPORT.md"
    sys.exit(check(fp))

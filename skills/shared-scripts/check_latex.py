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

    text = Path(filepath).read_text(encoding="utf-8")
    # 移除代码块、$$ 块、行内 $ 公式
    cleaned = re.sub(r"```.*?```", "", text, flags=re.DOTALL)
    cleaned = re.sub(r"\$\$[\s\S]*?\$\$", "", cleaned)
    cleaned = re.sub(r"\$[^\n$]+\$", "", cleaned)

    # 查找裸 LaTeX 命令
    PATTERN = re.compile(
        r"\\(tag|sqrt|hat|frac|tfrac|dot|begin|cdot|pm|in|exists|forall|big|cap)\b"
    )
    bad: list[tuple[int, str]] = []
    for i, line in enumerate(cleaned.split("\n"), 1):
        if PATTERN.search(line):
            bad.append((i, line.strip()[:80]))

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

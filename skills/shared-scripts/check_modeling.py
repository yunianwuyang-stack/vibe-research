#!/usr/bin/env python3
"""建模报告自检 - 替代 comp-modeling SKILL.md 中的 bash 验证块.

用法:
    python3 _utils/check_modeling.py [MODELING_REPORT.md] [PROBLEM_ANALYSIS.md]

退出码:
    0 - 无错误
    1 - 至少一项未通过
"""
from __future__ import annotations

import re
import sys
from pathlib import Path


def count_subproblems(filepath: str) -> int:
    p = Path(filepath)
    if not p.exists():
        return 0
    seen: set[str] = set()
    for line in p.read_text(encoding="utf-8").splitlines():
        if not re.match(r"^#{1,4}\s", line):
            continue
        m = re.search(r"问题[一二三四五六七八九十0-9]+", line)
        if m:
            seen.add(m.group())
        else:
            m2 = re.search(r"(problem|question)\s*[0-9]+", line.lower())
            if m2:
                seen.add(re.sub(r"\s+", "", m2.group()))
    return len(seen)


def main(modeling: str = "MODELING_REPORT.md",
         analysis: str = "PROBLEM_ANALYSIS.md") -> int:
    print("=== 建模报告自检 ===")
    errors = 0

    # 0. 文件存在 + 大小
    if not Path(modeling).exists():
        print(f"ERROR {modeling} 不存在！")
        return 1
    sz = Path(modeling).stat().st_size
    if sz >= 1500:
        print(f"OK {modeling} ({sz} bytes)")
    else:
        print(f"ERROR {modeling} 过小 ({sz} bytes，需>=1500) - 立即用 Write 工具产出，不要 end_turn")
        errors += 1

    text = Path(modeling).read_text(encoding="utf-8")

    # 1. 子问题覆盖
    prob = count_subproblems(analysis)
    model_secs = count_subproblems(modeling)
    print(f"赛题子问题数: {prob}, 建模报告覆盖: {model_secs}")
    if model_secs < prob:
        print("ERROR 有子问题未建模！")
        errors += 1

    # 2. 目标函数
    obj = len(re.findall(
        r"目标函数|min\b|max\b|最小化|最大化|objective|模型公式|数学模型",
        text, re.IGNORECASE,
    ))
    print(f"目标函数/模型公式出现次数: {obj}")
    if obj == 0:
        print("ERROR 未找到任何目标函数或模型公式！")
        errors += 1

    # 3. 约束
    c = len(re.findall(r"约束|s\.t\.|subject to|限制条件|≤|≥", text))
    print(f"约束条件出现次数: {c}")

    # 4. 符号说明
    if re.search(r"符号.*说明|符号.*含义|Symbol.*Description", text, re.IGNORECASE):
        print("OK 符号说明表存在")
    else:
        print("ERROR 缺少符号说明表")
        errors += 1

    # 5. 灵敏度
    if re.search(r"灵敏度|sensitivity|鲁棒性|robustness|稳健性", text, re.IGNORECASE):
        print("OK 灵敏度/鲁棒性分析方案存在")
    else:
        print("WARN 缺少灵敏度分析方案（评审加分项）")

    # 6. 图表预规划
    if re.search(r"图表预规划|fig_|TABLE_|DrawIO", text, re.IGNORECASE):
        print("OK 图表预规划已带入")
    else:
        print("ERROR 缺少图表预规划（paper-figure 步骤需要）")
        errors += 1

    # 7. 编程实现
    if re.search(r"编程|实现要点|Python|算法步骤|伪代码", text, re.IGNORECASE):
        print("OK 编程实现要点存在")
    else:
        print("WARN 缺少编程实现要点（comp-code 步骤需要）")

    # 8. 问题递进性提示
    print()
    print("=== 问题递进性检查 ===")
    print("人工审查：每个问题的结果是否比前一个有明显变化？")
    print("  特别检查：新增变量/资源/约束对目标函数是否有边际效益？")
    print("  如果没有 -> 回到 PROBLEM_ANALYSIS.md 的假设预检重新审视。")

    # 9. 假设参数化
    param = len(re.findall(r"参数化:|ALLOW_|ENABLE_|USE_|开关变量", text))
    print(f"假设参数化标记数: {param}")
    if param == 0:
        print("WARN 未找到假设参数化标记——关键假设应在代码中做成可切换参数")

    if errors:
        print(f"\n验证未通过，发现 {errors} 项 ERROR，必须修复后再结束本步骤。")
    else:
        print("\n所有必检项通过。")
    return errors


if __name__ == "__main__":
    m = sys.argv[1] if len(sys.argv) > 1 else "MODELING_REPORT.md"
    a = sys.argv[2] if len(sys.argv) > 2 else "PROBLEM_ANALYSIS.md"
    sys.exit(main(m, a))

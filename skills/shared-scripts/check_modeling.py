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


_CN_DIGITS = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}


def _normalize_id(token: str) -> str:
    """把 问题一 / 问题1 / Problem 1 / question1 统一成 'q1'，使跨文件口径一致。"""
    t = token.lower()
    m = re.search(r"([0-9]+)", t)
    if m:
        return f"q{int(m.group(1))}"
    m = re.search(r"([一二三四五六七八九十]+)", t)
    if m:
        cn = m.group(1)
        if cn == "十":
            n = 10
        elif cn.startswith("十"):
            n = 10 + _CN_DIGITS.get(cn[1:], 0)
        elif cn.endswith("十"):
            n = _CN_DIGITS.get(cn[0], 0) * 10
        elif "十" in cn:
            a, b = cn.split("十", 1)
            n = _CN_DIGITS.get(a, 0) * 10 + _CN_DIGITS.get(b, 0)
        else:
            n = _CN_DIGITS.get(cn, 0)
        return f"q{n}"
    return t


def subproblem_ids(filepath: str) -> set[str]:
    """从 Markdown 标题行提取子问题 id 集合（归一化）。

    与 _utils/count_subproblems.sh 口径一致：只看标题行，支持
    中文数字 / 阿拉伯数字 / Problem N / Question N。
    """
    p = Path(filepath)
    if not p.exists():
        return set()
    seen: set[str] = set()
    for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
        if not re.match(r"^#{1,4}\s", line):
            continue
        for m in re.finditer(r"问题\s*([一二三四五六七八九十]+|[0-9]+)", line):
            seen.add(_normalize_id(m.group(0)))
        for m in re.finditer(r"(problem|question)\s*([0-9]+)", line, re.IGNORECASE):
            seen.add(_normalize_id(m.group(0)))
    return seen


def declared_subproblem_count(filepath: str) -> int:
    """comp-prob-analysis 要求在报告开头写 “本赛题共 X 个子问题”，优先以此声明为准。"""
    p = Path(filepath)
    if not p.exists():
        return 0
    text = p.read_text(encoding="utf-8", errors="replace")
    m = re.search(r"本赛题共\s*([0-9]+|[一二三四五六七八九十]+)\s*个子问题", text)
    if not m:
        return 0
    return int(_normalize_id(m.group(1))[1:] or 0)


def count_subproblems(filepath: str) -> int:
    return len(subproblem_ids(filepath))


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

    # 1. 子问题覆盖（按归一化 id 做集合差，而不是只比大小——旧版 3 vs 3 但覆盖的是不同问题也会放行）
    prob_ids = subproblem_ids(analysis)
    model_ids = subproblem_ids(modeling)
    declared = declared_subproblem_count(analysis)
    prob = max(len(prob_ids), declared)
    model_secs = len(model_ids)
    print(f"赛题子问题数: {prob}（声明 {declared or '-'} / 标题 {len(prob_ids)}），建模报告覆盖: {model_secs}")
    missing = sorted(prob_ids - model_ids, key=lambda x: int(x[1:]) if x[1:].isdigit() else 0)
    if missing:
        print(f"ERROR 以下子问题在建模报告中没有对应标题: {', '.join(missing)}")
        errors += 1
    elif model_secs < prob:
        print("ERROR 有子问题未建模！")
        errors += 1

    # 2. 目标函数（\bmin\b/\bmax\b 前后都加词边界，避免 admin/climax 误命中）
    obj = len(re.findall(
        r"目标函数|\bmin\b|\bmax\b|最小化|最大化|objective|模型公式|数学模型",
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
    # \bfig_ 加词边界：旧版 'fig_' 会被 'config_' 命中而误判通过
    if re.search(r"图表预规划|FIGURE_MANIFEST|\bfig_|\bTABLE_|DrawIO", text, re.IGNORECASE):
        print("OK 图表预规划已带入")
    else:
        print("ERROR 缺少图表预规划（paper-figure 步骤需要）")
        errors += 1

    # 7. 编程实现
    if re.search(r"编程|实现要点|Python|算法步骤|伪代码", text, re.IGNORECASE):
        print("OK 编程实现要点存在")
    else:
        print("WARN 缺少编程实现要点（comp-code 步骤需要）")

    # 7.5 comp-modeling Step 5.5 要求的 5 项必备内容（comp-code 依赖这些做约束闭环）
    required_sections = [
        ("结果约束清单", r"结果约束清单|约束清单"),
        ("预期行为", r"预期行为"),
        ("异常处理预案", r"异常处理预案|异常预案"),
        ("方法指定", r"方法指定|方法唯一性"),
        ("验证检查点", r"验证检查点"),
    ]
    missing_sections = [name for name, pat in required_sections if not re.search(pat, text)]
    if missing_sections:
        print(f"WARN 缺少建模报告必备章节: {', '.join(missing_sections)}（comp-code 的 constraint_audit / structural_validation 依赖它们）")
    else:
        print("OK 5 项必备内容（约束清单/预期行为/异常预案/方法指定/验证检查点）齐全")

    # 7.6 优化类必须声明优化方向（min/max）——下游 auto_tune / local_search / 收敛审计都依赖它
    if re.search(r"目标函数|objective", text, re.IGNORECASE) and not re.search(
        r"\\(min|max)\b|\b(min|max)(imize)?\b|最小化|最大化", text, re.IGNORECASE
    ):
        print("WARN 存在目标函数但未明确写出优化方向（最小化/最大化）")

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

---
name: comp-code
description: "数学建模竞赛编程实现。根据建模报告编写代码、执行计算、收集结果。Use when user says \"编程\", \"写代码\", \"code implementation\"."
argument-hint: [modeling-report-or-topic]
allowed-tools: Bash(*), Read, Write, Edit, Grep, Glob, Agent
---

# 竞赛编程实现

根据建模报告编写代码并执行计算：**$ARGUMENTS**

## ⛔⛔⛔ 任务规模警示（先读这段, 再读后面所有内容）

**这不是简单任务。** 数学建模竞赛的 comp-code 步骤要把建模报告里**每个**子问题落地成可跑的代码 + 真实结果。
子问题数量由 MODELING_REPORT.md 决定（一问也可能, 多问也可能）, 不是固定的。

⛔ **判断你是否真的做完了**, 在 `end_turn` 之前自问：
1. MODELING_REPORT.md 里有几问？你是不是真的为每问都写了独立的 .py？
2. `figures/` 下是不是每问都有对应的 `problem_*_results.json` 且文件非空？
3. RESULTS.md 是不是已经存在, 包含每问的方法和数值结果？
4. 跑过完成铁律最后那段 bash 验证脚本了吗？

**任何一项答 "否" → 不要 `end_turn`, 继续干活。** 引擎会反复检测这些产物, 没产出会自动重新拉你回来重做, 与其被动重做不如一次做完。

⛔ **不要用 "我已经做了主要工作, 剩下的晚点再说" 的心态退出**。
"晚点" 在 LLM 单轮预算里不存在 — 一旦 `end_turn`, 你就被切断了, 下一次进来要重新读上下文 + 重新理解任务, 比当前继续干活贵得多。

## ⚡ 快速模式检测（第一步先跑，决定后面审查强度）

```bash
FAST_MODE=0
grep -q 'VIBE_FAST_MODE=1' CLAUDE.md 2>/dev/null && FAST_MODE=1
echo "FAST_MODE=$FAST_MODE"
```

**若 `FAST_MODE=1`（用户选了快速模式，速度优先）：**
- ✅ **仍必须做到**：每个子问题都写独立 .py、跑出真实结果、产出 `problem_*_results.json` + `RESULTS.md` + `code/main.py`、子问题全覆盖、结果不编造、通过下方"完成铁律"的产出验证。**这些是出稿底线，一个都不能省。**
- ❌ **跳过以下"追求完美"的耗时环节**（本 SKILL 后文出现时一律略过，不进入反复修正循环）：
  - `constraint_audit.py` 约束闭环审计、`validate_constraints()` 自动验证
  - `facts_audit.py` / `audit_facts_against_ocr` / `event_breakdown_audit.py` 三方比对与事件源审计
  - 结果合理性逐条审查（Q1-Q9）、建模-代码一致性深度对照（Q9）
  - 多算法交叉验证、双求解器对比、发现小偏差后的反复重跑打磨
  - 参数保真度审计（PROBLEM_FACTS.json 三方核对）——快速模式下正常取参、跑通即可
- 原则：**一次跑通、产出齐全即结束**，把深度质检留给用户。RESULTS.md 末尾的 `<!-- AUDIT_OK ... -->` 凭证仍可写（标注 `fast_mode=1`），但不因审计不过而反复重跑。

**若 `FAST_MODE=0`（默认，严格模式）：** 后文所有审计/审查环节照常执行，不得跳过。

## 输入

1. **MODELING_REPORT.md** — 建模报告（必须存在）
2. **PROBLEM_ANALYSIS.md** — 赛题分析报告
3. **TOPIC_PLAN.md** — 选题规划（统计建模，含图表预规划）
4. **user_data/** — 赛题附件数据

## ⛔⛔⛔ 完成铁律（最高优先级，违反则本步骤失败）

**本步骤必须产出 `RESULTS.md`（≥ 1KB）+ `code/main.py`（≥ 500 字节）+ 至少 1 个 `figures/*.json`**。

⛔ **结束前必跑产出验证**：
```bash
PASS=true
[ -f RESULTS.md ] && SZ=$(wc -c < RESULTS.md) || SZ=0
[ "$SZ" -ge 1024 ] && echo "✅ RESULTS.md ($SZ)" || { echo "❌ RESULTS.md 缺失或过小"; PASS=false; }
[ -f code/main.py ] && CSZ=$(wc -c < code/main.py) || CSZ=0
[ "$CSZ" -ge 500 ] && echo "✅ code/main.py ($CSZ)" || { echo "❌ code/main.py 缺失"; PASS=false; }
JSON_COUNT=$(ls figures/*.json 2>/dev/null | wc -l)
[ "$JSON_COUNT" -ge 1 ] && echo "✅ figures/*.json ($JSON_COUNT)" || { echo "❌ figures/*.json 缺失"; PASS=false; }

# 子问题数对照: 建模报告里有几问, code/ 和 figures/ 就要有几份对应产出
# 统一口径（调 _utils/count_subproblems.sh，与 comp-modeling / comp-paper-zh 完全一致）
EXPECTED_PROBS=$(bash _utils/count_subproblems.sh MODELING_REPORT.md)
ACTUAL_CODE=$(ls code/problem*.py 2>/dev/null | wc -l)
ACTUAL_JSON=$(ls figures/problem_*_results.json 2>/dev/null | wc -l)
[ "$EXPECTED_PROBS" -gt 0 ] && {
  [ "$ACTUAL_CODE" -ge "$EXPECTED_PROBS" ] || { echo "❌ 建模报告 $EXPECTED_PROBS 问, 但只有 $ACTUAL_CODE 个 problem*.py"; PASS=false; }
  [ "$ACTUAL_JSON" -ge "$EXPECTED_PROBS" ] || { echo "❌ 建模报告 $EXPECTED_PROBS 问, 但只有 $ACTUAL_JSON 个 problem_*_results.json"; PASS=false; }
}

[ "$PASS" != true ] && echo "⛔ 产出验证失败 — 必须补全所有缺失项后重新跑验证, 禁止 end_turn 结束本步骤"
```

## 工作流程

### Step 0: 恢复检查

检查 `RESULTS.md`、`code/*.py`、`figures/*_results.json` 是否已存在：
- RESULTS.md 完整（>1KB）-> 跳到结果验证
- code/*.py 存在但无 RESULTS.md -> 直接执行已有代码
- 什么都没有 -> 从头开始

### Step 1: 读取建模报告 + 建立实现清单 + 防错审查

从 MODELING_REPORT.md 提取每个子问题的求解算法、数学公式、输入输出要求、所需 Python 库。

**⛔ 防错审查（必做）：** 读取 `references/error_prevention_code.md`，根据 MODELING_REPORT.md 末尾标注的题型，对照对应章节的"必须验证"和"常见 Bug"条目。编码过程中逐项检查。

**⛔⛔ 约束闭环审计（写 RESULTS.md 前必做，最后一道防线）：** 读取 `_utils/error_prevention.md` 的"九、约束闭环校验"章节。按本题题设硬约束写一个 `constraint_audit.py`，**从最终写入的 results.json 重新计算所有约束**（不能信任优化器的 constraints_ok 字段）。任何 audit_fail：必须先修复模型/求解，再回头写稿。在 RESULTS.md 末尾必须有 `<!-- AUDIT_OK source=results.json rechecked_at=<timestamp> -->` 凭证；缺这一行直接判该子问题不通过。

> **罕见情形兜底**：若 PROBLEM_ANALYSIS.md 的硬约束清单注明「无硬约束」（纯回归/统计推断/描述性建模），跳过 `constraint_audit.py`，但仍需在 RESULTS.md 末尾留 `<!-- AUDIT_OK source=results.json rechecked_at=<timestamp> n_constraints=0 -->` 凭证以及一句话说明"本题无硬约束，已跑结果合理性自检（量纲/符号/数值范围）"。

**⛔⛔⛔ 题面参数保真度审计（参数密集型题目必做，最前置防线）：** 若工作区存在 `PROBLEM_FACTS.json`（comp-prob-analysis 阶段产出，题面参数 ≥ 20 时必产），编码前**必须**先按以下顺序做：
1. **以 PROBLEM_FACTS.json 为唯一权威源载入参数**：`facts = json.load(open('PROBLEM_FACTS.json'))`；所有数值常数必须从 facts 取，禁止裸数字字面量
2. **建命名常数**：例如 `P_DETECT_BIG_LASER_VS_MISSILE = facts['weapons'][0]['targets'][0]['p_detect']`，让代码读起来与题面表 1 行 1 直接对得上
3. **跑 `facts_audit.py`**（见 `_utils/error_prevention.md` 第十四章 14.4）：三方比对 PROBLEM_FACTS.json ↔ code/*.py ↔ paper/正文；找出疑似虚构 / 抄错的数字
4. **跑 `audit_facts_against_ocr` 做 OCR 客观比对**（见第十四章 14.7）：从 `user_data/*_extracted.txt`（workflow_engine 入口 Vision OCR 自动产出，AI 改不了）自动抽数字集合，与 PROBLEM_FACTS.json 数字集合比对；并验证 `_meta.source_files[].sha256` 与文件实际 sha256 一致（防 OCR 被篡改）。**facts 含 OCR 原文没有的数字 → 拒绝**（视为虚构）。
5. **每条 `rules` 段的 `machine_check` 必须有对应的 unit test**：例如"激光只能与激光协同"对应 `assert not any(plan.has_laser and plan.has_non_laser for plan in synergy_plans)`

**⛔⛔⛔ 事件源分类计数与反推（含多种来源累积同一聚合量时必做，最易出"约束都过但结论错位"bug）：**

详见 `_utils/error_prevention.md` 第十五章。

**触发条件**：题目里**多个来源**累积成**同一聚合量**时必须按本规则编码。常见形态：
- 多种伤害源（远程 / 近战 / 自爆）累加同一目标的总伤害
- 多种成本源（运输 / 等待 / 延误 / 罚款）累加同一总成本
- 多种来源人流（社区 / 输入 / 院内）累加同一新增量
- 多种胜负原因（主动击败 / 对手退出 / 裁定）累加同一胜率
- 多种漏检 / 拦截 / 通过原因累加同一统计指标

**编码硬性要求**：

1. **每个计数器只记录一种来源的事件**：模式 `count_by_<source>` / `total_<metric>_from_<source>`；禁止 `n_hit` / `events` / `struck` 这类二义命名（这是导致 bug 的根因——一个计数器同时被多个分支 append 不同来源的事件）
2. **每次离散事件落详细元组**：`events.append({'t': t, 'source': '<具体来源标识>', 'target': ..., 'value_per_event': <理论单次量值，从 facts 取>, 'cause_id': ...})`，禁止只 `flag=True` 或 `counter += 1`
3. **results.json 必须含**：
   - `events` 字段（所有离散事件列表）
   - `source_unit_value` 字典（每种 source 的理论单次量值，来自 PROBLEM_FACTS.json）
   - `totals` 字典（按 metric 分组的累计量）
   - `verb_to_sources` 字典（陈述动词到合法 source 集合的映射，供写稿步骤反查）
4. **代码末尾跑 `event_breakdown_audit.py`**（见 15.3）：
   - 总量 = Σ(per-event value)，差超 1e-3 拒绝
   - 按 source 分组每组 `count × theoretical_per_event ≈ actual_sum`，差超 1e-3 拒绝
5. **RESULTS.md 描述事件时必须标注**：计数器名 + 单次量值 + 事件次数 + 各 source 贡献
   - 例：`总量 X = N × <per_event_value>（来自 count_by_<source>，每次贡献 v）`
   - 让下游写稿步骤可以直接 grep 独立字段，无需脑补**⛔⛔⛔⛔ 防长上下文记忆漂移：强制生成 `code/params.py`（编码第一步）：**
   ```python
   # code/params.py — 自动生成，禁止手改
   import json
   from pathlib import Path
   _FACTS = json.loads(Path('PROBLEM_FACTS.json').read_text(encoding='utf-8'))
   # 命名常数（按 facts 结构展开所有数值）
   BIG_LASER_RANGE_KM = _FACTS['weapons'][0]['range_km']
   BIG_LASER_VS_MISSILE_P_DETECT = _FACTS['weapons'][0]['targets'][0]['p_detect']
   # ... 等等
   ```
   后续所有 code/*.py 必须 `from params import *`，**禁止裸数字字面量**（除白名单 0/1/2/-1/π/e 等纯数学常数）。这样即使上下文窗口压缩、AI"忘了"具体参数值，命名常数也只能从 params.py 取，不会凭印象重写。

**⛔ 加固版审计（参数密集型必跑，覆盖 6 个边缘漏洞）：**
   ```bash
   # comp-prob-analysis 阶段已跑过 --stage prob（OCR 比对）；本阶段跑完整审计含代码端
   # ⛔ 不要 tee 到 AUDIT_REPORT.md：facts_audit.py 自己会写 AUDIT_REPORT.md，两者同时写会互相覆盖成乱码；
   #    且管道后 $? 是 tee 的退出码（恒为 0），审计失败会被静默吞掉。用 PIPESTATUS[0] 取 python 的退出码。
   python3 _utils/facts_audit.py --stage code 2>&1 | tee _tmp/facts_audit.log
   RC=${PIPESTATUS[0]}
   # grep -c 无匹配时会输出 0 且退出码 1，再 `|| echo 0` 会得到 "0\n0" 两行 → 用 || true
   n_suspicious=$(grep -cE '^- (⛔|⚠)' AUDIT_REPORT.md 2>/dev/null || true)
   n_suspicious=${n_suspicious:-0}
   if [ "$RC" -eq 1 ]; then
     echo "⛔ facts_audit 有 fatal 项，必须先修复再写凭证（不要带着 fatal 结束本步骤）"
   fi
   # 凭证里加 n_suspicious_numbers 字段（写稿阶段拦截非零）
   echo "<!-- AUDIT_OK source=results.json rechecked_at=$(date -Iseconds) n_constraints=$N n_suspicious_numbers=$n_suspicious facts_audit_rc=$RC -->" >> RESULTS.md
   ```
   含：OCR 比对（复查，防中途篡改）/ schema 校验 / 派生值验算 / 代码端裸数字审计 / 图脚本数据溯源 / 子问题字段隔离。详见 `_utils/error_prevention.md` 第十四章 14.6-14.7。

**📚 按题型按需调用其他审计章节（`_utils/error_prevention.md`）**：
- **第十章 单位审计**（`unit_audit.py`）：含物理量 / 工程量 / 经济量的题 — 扫描代码裸常数，比对 PROBLEM_ANALYSIS.md 的变量-单位登记表
- **第十一章 可复现性**（`repro_audit.py` + `set_all_seeds`）：含随机数 / 启发式 / 蒙特卡洛 / 神经网络 / MCMC 的题 — **代码入口必须先调 `set_all_seeds(seed)`**；results.json 头部必须含 `seed / run_id / python / numpy / torch` 等版本信息；每张图 figures/*.json 必含 seed 字段
- **第十二章 数据泄露**（`leakage_audit.py`）：含训练 / 测试 / 时序预测 / 因果识别的题 — 切分必须早于任何 `fit()`，时序题禁用 KFold shuffle，检测未来信息特征
- **第十三章 求解器收敛**（`solver_audit.py`）：含数值优化 / 启发式 / MCMC 的题 — 不要盲信 `success=True`，必须检查梯度范数 / 多重起点方差 / 收敛曲线尾段 / 多链 R̂ 等"二阶证据"

**⛔ MANDATORY: 输出实现清单，后续逐项打勾：**
```
IMPLEMENTATION CHECKLIST (from MODELING_REPORT.md):
[ ] 问题1: [算法名] — 输入: [xxx], 输出: [yyy], 库: [zzz]
[ ] 问题2: [算法名] — 输入: [xxx], 输出: [yyy], 库: [zzz]
[ ] 问题3: [算法名] — 输入: [xxx], 输出: [yyy], 库: [zzz]
[ ] 灵敏度分析: [参数列表]
```
每完成一个子问题，更新清单状态。

### Step 1.5: 提取图表预规划

**⛔ MANDATORY: 读取规划文档的图表预规划，了解下一步 paper-figure 需要生成哪些图表。**

comp-code 不生成 PDF 图表，但需要确保输出的 JSON 数据能支撑这些图表。

```bash
echo "=== 图表预规划 ==="
for plan in TOPIC_PLAN.md PROBLEM_ANALYSIS.md MODELING_REPORT.md; do
    [ -f "$plan" ] || continue
    echo "--- $plan ---"
    grep -i 'fig_\|图表\|TABLE_\|TikZ\|预规划\|figure' "$plan" | head -30
done
```

记录规划中的图表清单，确保每个图表对应的数据都会在分析过程中输出到 JSON。

**⛔ 图表语言规则：** 中文论文（统计建模/数模竞赛）的图表 axis label、legend、annotation 必须用中文。例如 `ax.set_xlabel('迭代次数')` 而不是 `ax.set_xlabel('Iterations')`。但这是 paper-figure 的事——comp-code 只需确保 JSON 数据的 key 名有意义即可。

### Step 2: 环境准备

检查 Python，安装必要库（numpy, pandas, scipy, matplotlib, scikit-learn, statsmodels, networkx）。

### Step 2.5: 数据读取验证（有附件数据时必做）

**⛔ 写任何求解代码之前，先写一个独立的数据验证脚本，确认数据读取正确：**

```python
# code/data_check.py — 数据读取验证（先跑这个，再写求解代码）
import pandas as pd
import os, glob

data_files = glob.glob('user_data/*.csv') + glob.glob('user_data/*.xlsx') + glob.glob('user_data/*.xls')
print(f"找到 {len(data_files)} 个数据文件")

for f in data_files:
    print(f"\n=== {os.path.basename(f)} ===")
    try:
        df = None
        if f.endswith('.csv'):
            # 尝试多种编码（utf-8-sig 可去掉 Excel 导出的 BOM，避免首列名变成 '\ufeff列名'）
            for enc in ['utf-8-sig', 'utf-8', 'gbk', 'gb18030', 'latin-1']:
                try:
                    df = pd.read_csv(f, encoding=enc)
                    print(f"  编码: {enc}")
                    break
                except UnicodeDecodeError:
                    continue
            if df is None:
                raise RuntimeError('所有编码均无法解码')
        else:
            # 多 sheet 的 Excel 只读第一个 sheet 会漏数据：先列出所有 sheet
            sheets = pd.ExcelFile(f).sheet_names
            if len(sheets) > 1:
                print(f"  ⚠ 含 {len(sheets)} 个 sheet: {sheets}（下面只展示第一个，其余需单独读取）")
            df = pd.read_excel(f, sheet_name=sheets[0])
        
        print(f"  形状: {df.shape}")
        print(f"  列名: {list(df.columns)}")
        print(f"  数据类型:\n{df.dtypes}")
        print(f"  缺失值:\n{df.isnull().sum()[df.isnull().sum() > 0]}")
        print(f"  前3行:\n{df.head(3)}")
        
        # 数值列的基本统计
        num_cols = df.select_dtypes(include='number').columns
        if len(num_cols) > 0:
            print(f"  数值统计:\n{df[num_cols].describe()}")
            # 检查异常值（注意运算符优先级：旧写法 `a and b or c or d` 会让所有"数量/距离"列都误报负值）
            NONNEG_HINTS = ('价格', '数量', '距离', '成本', '人数', '重量', '面积', '时间', '速度', '容量')
            for col in num_cols:
                if df[col].min() < 0 and any(k in str(col) for k in NONNEG_HINTS):
                    print(f"  ⚠ {col} 有负值（{df[col].min()}），检查是否合理")
                if df[col].isnull().sum() > len(df) * 0.5:
                    print(f"  ⚠ {col} 缺失率 > 50%")
    except Exception as e:
        print(f"  ❌ 读取失败: {e}")
```

**执行 data_check.py 后，确认以下几点再继续：**
1. 所有数据文件都能正确读取（编码、分隔符无误）
2. 列名和题目描述一致（不是乱码或错位）
3. 数据规模和题目描述一致（行数、列数）
4. 缺失值和异常值已识别，后续代码中有处理方案

### Step 3: 代码目录结构

```
code/
  main.py          # 主程序（串联所有子问题）
  problem1.py      # 子问题 1
  problem2.py      # 子问题 2
  utils.py         # 公共工具
  requirements.txt
```

### Step 3.0: ⛔⛔⛔ 模块导入铁律（违反必失败）

**问题本质：** code/ 下的脚本互相 `import` 时，从不同目录调用会导致 sys.path 不包含 `code/`，
报 `ModuleNotFoundError: No module named 'utils'` / `'problem1'` 等。这是历史上最高频的失败原因。

**⛔ 规则 1：每个 .py 文件顶部必须有自举 import 头（在所有 import 之前）：**

```python
# ⛔ 自举模块路径（让 sibling import 不依赖调用方式）
import os, sys
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

# 之后才能写其它 import
import numpy as np
import utils as u   # 现在 utils.py 跟当前文件同目录就一定能 import 到
```

**⛔ 规则 2：执行任何 code/ 下的脚本必须 `cd code && python xxx.py`，禁止 `python code/xxx.py`**

```bash
# ✅ 正确（无论 utils 在不在都能跑）
cd code && python data_check.py && cd ..
cd code && python problem1.py && cd ..
cd code && python main.py && cd ..

# ❌ 错误：sys.path 不含 code/，sibling import 会爆 ModuleNotFoundError
python code/problem1.py
python -m code.problem1
```

**⛔ 规则 3：写入子问题脚本前先写 `code/utils.py` 雏形（哪怕暂时为空），避免"先写 problem1 → import utils → utils 还没创建"的瞬时错。**

**⛔ 规则 4：跑代码必须用 `set -e` + 显式检查 exit code，不能在脚本失败后假装结果有效：**

```bash
mkdir -p _tmp
cd code
# ⛔ 必须加 -o pipefail：只有 set -e 时，`python x.py | tee log` 的退出码是 tee 的（恒 0），脚本崩了也不会停
set -eo pipefail
python data_check.py 2>&1 | tee ../_tmp/data_check.log
python problem1.py 2>&1 | tee ../_tmp/problem1.log
[ -f ../figures/problem_1_results.json ] || { echo "❌ problem1 未产出结果 JSON"; exit 1; }
cd ..
```


### Step 4: 逐子问题编写和执行

**必须按顺序逐问求解：编写 -> 执行 -> 验证 -> 下一问。**

**⛔ Step 4.0: 上游一致性检查（开始编码前必做）：**
```bash
echo "=== 上游一致性检查 ==="
# 检查 MODELING_REPORT.md 是否存在
[ -f MODELING_REPORT.md ] && echo "✅ MODELING_REPORT.md 存在" || { echo "❌ MODELING_REPORT.md 不存在！"; exit 1; }
# 提取子问题数量（统一口径：只数标题行，避免正文出现次数导致虚高）
PROB_COUNT=$(bash _utils/count_subproblems.sh PROBLEM_ANALYSIS.md)
MODEL_COUNT=$(bash _utils/count_subproblems.sh MODELING_REPORT.md)
echo "赛题分析子问题数: $PROB_COUNT, 建模报告子问题数: $MODEL_COUNT"
[ "$MODEL_COUNT" -lt "$PROB_COUNT" ] && echo "⚠ 建模报告覆盖的子问题数少于赛题分析，请检查是否遗漏"
# 提取建模报告推荐的方法
echo "--- 建模报告推荐方法 ---"
grep -i '算法\|方法\|模型.*选择\|求解.*策略' MODELING_REPORT.md 2>/dev/null | head -10
echo "--- 编程实现时必须使用上述方法，或明确说明替代理由 ---"
```

代码性能要求：
- 优先使用 numpy 向量化运算，避免 Python 原生 for 循环遍历大数据
- 数据量大（>1000 行）必须用向量化或矩阵运算
- 每个脚本执行前后打印进度信息
- 如果代码跑超过 3 分钟，立即重写优化版本

自主判断数据来源：
- 有附件数据（`user_data/*.csv` 存在）：从文件读取
- 无附件数据（纯建模题）：根据 MODELING_REPORT.md 自行构造参数

每个子问题：
1. 编写独立 Python 文件
2. 执行并检查输出
3. 验证结果合理性
4. 保存结果到 `figures/problem_N_results.json`
5. 结果异常则修改代码重跑

---

### Step 4.5: ⛔⛔⛔ 每问跑完后的自检流程（核心，每个子问题都必须做）

**这是本步骤防失败的关键。每完成一问的代码 + JSON 后，必须按下面流程做自检，
满足要求才能进入下一问。** 不要写完所有问题再统一自检 — 那样发现问题要回头改, 浪费 turn 预算。

每个子问题跑完, 立即按以下顺序 Read 自检文件并按其要求验证：

**第 1 步：必读（所有题型）**

```
Read references/checks/_index.md         # 自检总索引（仅第 1 问读, 后续可跳过）
Read references/checks/consistency.md    # 建模-代码契约 + 物理参数引用 + 自动化约束验证代码
Read references/checks/sanity_check.md   # 自动数值审查 + 9 问背景审查 + 编程 Bug 排查
```

**第 2 步：根据本问的题型选读 1 个分类自检文件**

| 本问类型 | Read 哪个 |
|---|---|
| 优化类（调度/选址/路径/分配/规划/求最优值）| `references/checks/optimization.md`（含 5 层求解 + 结构性验证）|
| 预测类（时间序列/回归/分类）| `references/checks/prediction.md` |
| 评价类（TOPSIS/AHP/熵权法/排名打分）| `references/checks/evaluation.md` |
| 物理/几何（碰撞检测/动力学/ODE/SAT 检测）| `references/checks/physical.md` |
| 统计/实证/图论 | `references/checks/sanity_check.md` 末尾的 S/G 区段已涵盖 |

**第 3 步：把自检结论写到 `_tmp/problem_N_check.md`，每条 ✅/⚠️/❌**

**第 4 步：处理 ❌**

- 任何 ❌ → 修代码 → 重跑 → 重新自检
- 同一问最多修 3 轮，3 轮还不通过 → 在 RESULTS.md 中标注"建模需修正"，继续下一问

**第 5 步：全部 ✅ 或最多 ⚠️ → 把本问的方法 + 关键结果写到 RESULTS.md 对应章节，立即下一问**

⛔ **关键纪律**：
- 自检时**不能依赖记忆里的规则**，必须显式 Read 上面列出的 .md 文件 — 这是本拆分设计的目的
- 每问都要走完 Step 4.5 才能开始下一问，不要跳过、不要合并、不要等到所有问都跑完再统一自检

### Step 5: 编写主程序

`code/main.py` 串联所有子问题，汇总结果到 `figures/all_results.json`。

### Step 5.5: 模型检验（根据题型自主判断）

根据题目类型，选择合适的模型检验方式。不是所有题都需要灵敏度分析 — 自己判断：

- **优化类**（调度/选址/路径）→ 灵敏度分析：关键参数 ±20% 对目标函数的影响
- **预测类**（时间序列/回归）→ 交叉验证 + 残差分析 + 多模型对比
- **评价类**（TOPSIS/AHP/熵权法）→ 权重稳定性分析：微调权重看排名是否变化
- **图论/网络类** → 参数灵敏度（边权/容量变化对最优解的影响）
- **统计/实证类** → 稳健性检验（替换变量、子样本、工具变量）

如果判断需要灵敏度分析，执行以下步骤：

Read MODELING_REPORT.md for the sensitivity analysis plan. For each key parameter identified:

1. Write `code/sensitivity_analysis.py` that varies the parameter across a range (e.g., ±20% in 10 steps)
2. For each parameter value, re-run the model and record the objective function value
3. Save results to `figures/sensitivity_results.json`:
```json
{
  "parameter_name": {"values": [...], "objective": [...]},
  "parameter_name2": {"values": [...], "objective": [...]}
}
```
4. Execute the script and verify results are reasonable

This data is required by paper-figure to generate tornado charts and sensitivity curves, and by comp-paper-zh for the 灵敏度分析 chapter.

### Step 6: 结果验证 + 实现清单对照

- 数值范围：概率在[0,1]、非负数、非 NaN/Inf
- 一致性：子问题间不矛盾
- 收敛性：优化器是否收敛
- 统计检验：R2在[0,1]、p值在[0,1]

**⛔ MANDATORY: 对照 Step 1 的实现清单，逐项验证：**
```bash
echo "=== 实现清单对照 ==="
echo "检查每个子问题的结果文件是否存在且非空："
for f in figures/problem_*_results.json figures/all_results.json; do
    if [ -f "$f" ] && [ -s "$f" ]; then
        echo "  ✅ $f ($(wc -c < "$f") bytes)"
    else
        echo "  ❌ $f — MISSING or EMPTY"
    fi
done
# 灵敏度分析数据是软性要求(优化类必做, 其他题型可选)
if [ -f figures/sensitivity_results.json ]; then
    echo "  ✅ figures/sensitivity_results.json (灵敏度分析数据)"
elif [ -f MODELING_REPORT.md ] && grep -qE '灵敏度|sensitivity' MODELING_REPORT.md; then
    echo "  ⚠ figures/sensitivity_results.json — 建模报告提到灵敏度但未产出, 优化类必须补"
fi
echo ""
echo "检查代码文件是否存在："
for f in code/*.py; do
    [ -f "$f" ] && echo "  ✅ $(basename $f)" || echo "  ❌ $(basename $f)"
done
```

**如果有 ❌，必须回去补完再继续。** 特别注意：
- `figures/all_results.json` 必须存在（paper-figure 依赖它画图）
- 每个子问题的 `figures/problem_N_results.json` 必须存在
- `figures/sensitivity_results.json` 仅当题目/建模报告涉及灵敏度分析时必须（优化类必做）

### Step 7: 结果汇总

保存到 `RESULTS.md`：每个子问题的方法、关键结果、数据文件路径、代码文件清单。

### Step 7.5: 数据输出完整性检查（⛔ 必须通过）

确保所有分析结果都保存为 JSON/CSV，供下一步 paper-figure 读取画图：

```bash
echo "=== 数据输出完整性检查 ==="
echo ""
echo "JSON 数据文件（paper-figure 的输入）："
ls -la figures/*.json 2>/dev/null || echo "  (无)"
echo ""
echo "TABLE 文件："
ls -la figures/TABLE_*.tex 2>/dev/null || echo "  (无)"
```

**⛔ MANDATORY：**
```bash
MISSING=0
# all_results.json 必须存在
if [ -f figures/all_results.json ] && [ -s figures/all_results.json ]; then
    echo "  ✅ figures/all_results.json"
else
    echo "  ❌ figures/all_results.json — MISSING or EMPTY"
    MISSING=$((MISSING+1))
fi
# 灵敏度分析数据（数模竞赛必须）
if [ -f figures/sensitivity_results.json ]; then
    echo "  ✅ figures/sensitivity_results.json"
else
    echo "  ⚠ figures/sensitivity_results.json — not found (required for sensitivity chapter)"
fi
echo "Missing: $MISSING"
```

**如果 ❌，必须回去补完再继续。**

**⛔ 不要在这一步生成 PDF 图表或 latex_includes.tex——那是 paper-figure 的职责。**

## 关键规则

- **comp-code 只负责数据采集、统计分析、输出结果数据（JSON/CSV）。不画图。**
- **⛔ 禁止在分析代码中生成 PDF 图表。** 所有 `plt.savefig()`、`save_fig()` 调用都不应该出现在 comp-code 的代码里。如果分析过程中需要可视化验证结果，用 `plt.show()` 看一眼就行，不要保存 PDF。
- **图表 PDF 全部由下一步 paper-figure 生成。** paper-figure 会读取 comp-code 输出的 JSON 数据，按 recipe 系统生成高质量 PDF。
- **⛔ 求解器/优化器超时设置：** 不要设太短的超时（如 120 秒）。竞赛数据量可能很大，求解器需要足够时间。推荐设置：
  - 小规模问题（变量 <100）：`timeout=300`（5 分钟）
  - 中规模问题（变量 100-1000）：`timeout=600`（10 分钟）
  - 大规模问题（变量 >1000）：`timeout=1200`（20 分钟）
  - 所有求解器都必须打印进度（每 30 秒输出一次当前最优解），防止无输出超时被系统杀掉
- 主输出文件：`RESULTS.md` + `figures/*.json`
- 临时文件放 `_tmp/` 目录
- 代码必须能运行：写完必须执行验证
- 结果必须保存为 JSON/CSV 文件（供 paper-figure 读取画图）

<data_quality>
### Data generation quality (when generating/simulating data without user uploads)

⛔ **先判断是否真的允许生成数据**：竞赛题若给了附件数据，禁止用模拟数据替代；若题目要求"自行采集真实数据"（如统计建模大赛），必须采集真实公开数据并标注来源，禁止模拟。
只有"纯建模题、题面只给参数不给数据"时才允许按题面参数构造仿真输入。

⛔ **模拟数据必须显式打标，禁止伪装成真实数据**：
- 每个由模拟数据得到的 `figures/*.json` 必须含 `"data_source": "synthetic"` 与生成方式（分布/参数/seed）
- RESULTS.md 对应小节标题加 `（仿真数据）`，写稿步骤据此在论文中如实说明
- 禁止为了"让方法看起来更好"而调整模拟数据；对比实验中方法优劣必须是模型/算法带来的，不是数据设计出来的

When no user data is available and you need to generate or simulate data:

1. **Realistic ranges**: values must match the problem domain — e.g., temperature in °C not arbitrary 0-1, population in millions not random integers
2. **Meaningful patterns**: data should show the trends/relationships the model is designed to capture — e.g., if modeling seasonal demand, the data should have seasonal patterns
3. **Visualization-friendly**: design data so the resulting figures look informative and professional:
   - Avoid extreme outliers that compress the main data into a tiny range
   - Ensure different methods/groups have visible but not identical differences (5-20% gaps, not 0.1% or 500%)
   - Include enough data points for smooth curves (≥50 for line plots, ≥200 for distributions)
   - For method comparison: do NOT tune the synthetic data so that the proposed method wins; generate data from the stated problem mechanism only, run every method on the same seeds, and report whatever ranking results (with CI). If the proposed method loses, that is a finding to report, not a data problem to fix
4. **Consistent with problem statement**: all generated numbers must be traceable to the problem description — if the problem says "30 provinces", generate 30 data points, not 10
5. **Reproducible**: set random seeds (`np.random.seed(42)`) so results are deterministic
</data_quality>

- 代码要有注释（附录评审加分项）
- 数据路径用相对路径
- 基本异常处理，一个子问题失败不能全崩
- requirements.txt 必须生成
- 大文件用 Bash heredoc 分块写入

## 详细参考（按需 Read，不要一次全读）

主流程已在 Step 0–7.5。以下是按主题搬到 `references/checks/` 的深度参考，按 Step 4.5 的指引在每问跑完时打开：

| 触发场景 | Read 哪个文件 |
|---|---|
| 第 1 问开始前（仅 1 次）| `references/checks/_index.md` |
| 任何子问题跑完 | `references/checks/consistency.md` |
| 任何子问题跑完 | `references/checks/sanity_check.md` |
| 优化类子问题 | `references/checks/optimization.md`（含 5 层求解 + 结构性验证）|
| 预测类子问题 | `references/checks/prediction.md` |
| 评价类子问题 | `references/checks/evaluation.md` |
| 物理/几何题 | `references/checks/physical.md` |
| 写代码遇到具体 bug | `references/error_prevention_code.md`（按题型查防错条目）|

⛔ **每问的自检流程见 Step 4.5，不能跳过、不能合并、不能等到所有问跑完才统一自检。**

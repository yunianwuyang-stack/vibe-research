---
name: paper-figure
description: "Generate publication-quality figures and tables from experiment results. Use when user says \"画图\", \"作图\", \"generate figures\", \"paper figures\", or needs plots for a paper."
argument-hint: [figure-plan-or-data-path]
allowed-tools: Bash(*), Read, Write, Edit, Grep, Glob, Agent, mcp__codex__codex, mcp__codex__codex-reply
---

# Paper Figure: Publication-Quality Figure Generation

Generate figures and tables from data: **$ARGUMENTS**

## 用户数量硬下限

```bash
source .env_skill 2>/dev/null || true
echo "MIN_FIGURES=${MIN_FIGURES:-auto} MIN_TABLES=${MIN_TABLES:-auto}"
```

若 `MIN_TABLES` 是大于 0 的整数，必须生成至少该数量的独立数据表，并使用
`figures/TABLE_<id>.tex` (PDF) 或 `figures/TABLE_<id>.md` (DOCX) 命名。同一 `<id>` 的多格式副本只算
1 个表格。引擎会按唯一 `<id>` 生成 `QUANTITY_MANIFEST.json` 并做终端门禁。

## Constants

- **FIG_DIR = `figures/`**
- **FORMAT = `pdf`** (vector, suitable for LaTeX)
- **DPI = 300**
- **CUSTOM_REQUIREMENTS** — User-specified requirements, highest priority.

<tools_and_style>
## Tools and Style

`shared-scripts/plot_utils.py` is the **MANDATORY** style baseline. Every `gen_fig_*.py` script **MUST** begin with `from _utils.plot_utils import setup_style, save_fig, PALETTE, COLORS; setup_style()`.

**After `setup_style()` you have full creative freedom**:
- ✅ Use plot_utils helper functions (`heatmap`, `bar_compare`, `forest_plot`, ...) for common chart types
- ✅ OR use **raw matplotlib / seaborn** for any chart type not in plot_utils (Sankey, Treemap, 3D, Bivariate Choropleth, custom layouts ...)
- ✅ Use `PALETTE[n]` / `COLORS['up'/'down'/'highlight'/'ref_line'/'grid'/'text']` as the primary color source
- ✅ **A small number of hand-picked coordinated hex colors are OK** for special highlights / reference lines (≤ 2 per figure, must visually harmonize with the active palette)
- ❌ Never use matplotlib's `tab10` defaults — bright blue `#1f77b4`, orange `#ff7f0e`, green `#2ca02c` are the unmistakable "default style" reviewers spot in 1 second
- ❌ Never use CSS bright color names (`'blue'`, `'red'`, `'green'`, `'orange'`) — same `tab10` aesthetic
- ❌ Never use ugly colormaps (`RdYlGn` traffic-light, `RdBu_r` too dark, `dark_background` theme)

⛔⛔ **The real rule**: figures must NOT look like "ran with matplotlib defaults". `setup_style()` swaps in the `elegant` palette (`#7AAEC8` dusty-blue / `#E8945A` warm-orange / `#7BC8A4` mint / `#9B8EC4` lavender) which is calibrated for academic publication. You may augment with creative coordinated hex (e.g. `#FFB347` warm highlight, `#A8DADC` accent) — what's forbidden is the *specific* combination that says "I never customized".

**Quality floor**: 300 DPI PDF, no in-figure title (`plt.title`), font ≥9pt, grayscale-distinguishable, **`figure_check.sh` exit code 0** (CRITICAL only — INFO/WARNING don't block).

**Color palette and recipes**: read `_utils/figure_style_guide.md` (color schemes) and `_utils/figure_recipes_*.md` (code examples).

plot_utils functions: `setup_style`, `save_fig`, `heatmap`, `forest_plot`, `trend_plot`, `bar_compare`, `distribution_plot`, `scatter_plot`, `residual_diagnostic`, `multi_line_plot`, `box_plot`, `radar_plot`, `subplot_grid`

Stats tables: `stats_utils.py` provides `regression_table`, `descriptive_table`, `correlation_table`.
</tools_and_style>

## ⛔⛔⛔ Output Contract (highest priority)

**Must produce all planned figures (per PAPER_PLAN.md or skill-specific plan)** as `figures/fig_*.png/pdf` plus `figures/latex_includes.tex` (or, in docx mode, the same PNGs without latex_includes.tex requirement).

⛔ **数据图命名规范**：本步骤画的是**数据图**（柱状/折线/热力/散点等），命名 `fig_<语义>`，但**避开架构/流程图专用前缀**：`fig_arch` / `fig_flow` / `fig_roadmap` / `fig_pipeline` / `fig_framework` / `fig_network` / `fig_state` / `fig_decision` / `fig_overview` 等（这些归 paper-figure-drawio）。例如流速图用 `fig_velocity` 而非 `fig_flow_rate`、状态分布用 `fig_status_dist` 而非 `fig_state_traj`。否则本步骤的产出对账会把它当架构图跳过，导致漏画不报错。

⛔ **特殊豁免**：如果 PAPER_PLAN.md 明确写"无图表"或图表清单为空（纯文字综述/思辨论文），允许 figures/ 为空，但**必须**写一个空的 `figures/latex_includes.tex` (`touch figures/latex_includes.tex; mkdir -p figures`) 让下游知道这步跑过了。

⛔ **MUST run output verification before ending**:
```bash
PASS=true
mkdir -p figures
FIG_PNG=$(ls figures/fig_*.png 2>/dev/null | wc -l)
FIG_PDF=$(ls figures/fig_*.pdf 2>/dev/null | wc -l)
TOTAL=$((FIG_PNG + FIG_PDF))

# ⛔⛔⛔ 优先按 FIGURE_MANIFEST 对账 (规划了几张就必须画几张, 少一张都报错)
PLAN_FILE=""
for f in PROBLEM_ANALYSIS.md PAPER_PLAN.md MODELING_REPORT.md; do
  [ -f "$f" ] && grep -q '<!-- BEGIN FIGURE_MANIFEST -->' "$f" && { PLAN_FILE="$f"; break; }
done

if [ -n "$PLAN_FILE" ]; then
  START=$(grep -n '<!-- BEGIN FIGURE_MANIFEST -->' "$PLAN_FILE" | head -1 | cut -d: -f1)
  END=$(grep -n '<!-- END FIGURE_MANIFEST -->' "$PLAN_FILE" | head -1 | cut -d: -f1)
  # ⛔ 只对「数据图」硬对账。流程/架构/路线图和 tikz_ 由 paper-figure-drawio 子流程产出，
  # 不属于本步骤职责。按 manifest「数据图章节」标题抓该章节下的图名(权威), 不靠前缀排除——
  # 旧排除法对 fig_data_pipeline/fig_model_arch 这类「关键词在中间」的架构图排不掉, 会把它们
  # 误当数据图纳入对账 → 本步骤因"缺架构图"永远自检不过而空转。按章节抓则精准只对数据图。
  EXPECTED_FIGS=$(sed -n "${START},${END}p" "$PLAN_FILE" | awk '
      /^[[:space:]]*\*\*/ {
          if ($0 ~ /数据图/ || tolower($0) ~ /matplotlib|gen_fig/) cap=1; else cap=0;
          next
      }
      cap && match($0, /^[[:space:]]*-[[:space:]]+fig_[a-zA-Z0-9_]+/) {
          s=substr($0, RSTART, RLENGTH); sub(/^[[:space:]]*-[[:space:]]*/, "", s); print s
      }')
  TOTAL_EXPECTED=$(echo "$EXPECTED_FIGS" | grep -c . )
  MISSING_FIGS=""
  for name in $EXPECTED_FIGS; do
    ls figures/${name}.png figures/${name}.pdf figures/${name}.drawio 2>/dev/null | head -1 | grep -q . || MISSING_FIGS="$MISSING_FIGS $name"
  done
  MISSING_COUNT=$(echo "$MISSING_FIGS" | wc -w)
  if [ "$MISSING_COUNT" -gt 0 ]; then
    echo "❌ FIGURE_MANIFEST 对账失败(仅数据图): 规划 $TOTAL_EXPECTED 张, 缺失 $MISSING_COUNT 张:"
    for m in $MISSING_FIGS; do echo "    - $m"; done
    echo "⛔ 必须把这些数据图全部产出才能结束 paper-figure 步骤(流程/架构/路线图由 paper-figure-drawio 负责, 不在此列)"
    PASS=false
  else
    echo "✅ FIGURE_MANIFEST 数据图全部产出: $TOTAL_EXPECTED 张(流程/架构图归 paper-figure-drawio)"
  fi
else
  # 没有 MANIFEST 时退回旧的宽松检查
  PLAN_HAS_FIG=$(grep -E '^\s*-?\s*fig_|图表清单|figures/fig_' PAPER_PLAN.md PROBLEM_ANALYSIS.md 2>/dev/null | wc -l)
  if [ "$TOTAL" -ge 1 ]; then
    echo "✅ figures/fig_*.png/pdf ($TOTAL) [no FIGURE_MANIFEST, weak check]"
  elif [ "$PLAN_HAS_FIG" -eq 0 ]; then
    echo "✓ 规划无图表, 创建占位 latex_includes.tex"
    touch figures/latex_includes.tex
  else
    echo "❌ 规划要求图表但未生成"
    PASS=false
  fi
fi

# 半完成状态检测: 数据备好但没画图
HAS_PLOT_DATA=$([ -f figures/_plot_data.json ] && echo 1 || echo 0)
HAS_GEN_FIG=$(ls figures/gen_fig_*.py 2>/dev/null | wc -l)
HAS_PREP_DATA=$(ls figures/prep_plot_data.py figures/prep_*.py 2>/dev/null | wc -l)
if [ "$HAS_PLOT_DATA" -eq 1 ] && [ "$HAS_GEN_FIG" -eq 0 ]; then
  echo "❌ 半完成: _plot_data.json 存在但 gen_fig_*.py 全无 (备好食材没下锅)"
  PASS=false
fi
if [ "$HAS_PREP_DATA" -ge 1 ] && [ "$HAS_GEN_FIG" -eq 0 ]; then
  echo "❌ 半完成: prep_plot_data.py 存在但 gen_fig_*.py 全无 (数据准备完没画图)"
  PASS=false
fi

MODE=$(grep -q "Word（.docx）\|docx mode" CLAUDE.md 2>/dev/null && echo docx || echo pdf)
if [ "$MODE" = "pdf" ] && [ ! -f figures/latex_includes.tex ]; then
    touch figures/latex_includes.tex
fi
[ "$PASS" != true ] && echo "⛔ Output verification FAILED — must complete before ending"
```

## Workflow

### Step 0: 恢复检查（断线重跑必读）

⛔ **本步骤可能因为断线/手动重跑被多次启动**。每次启动前**必须**先扫描已有产物 + **按 FIGURE_MANIFEST 对账**：

```bash
echo "=== 工作区扫描 ==="
HAS_PNG=$(ls figures/fig_*.png 2>/dev/null | wc -l)
HAS_PDF=$(ls figures/fig_*.pdf 2>/dev/null | wc -l)
HAS_TIKZ=$(ls figures/tikz_*.pdf 2>/dev/null | wc -l)
HAS_DRAWIO=$(ls figures/fig_*.drawio 2>/dev/null | wc -l)
HAS_GEN_FIG=$(ls figures/gen_fig_*.py 2>/dev/null | wc -l)
HAS_PLOT_DATA=$([ -f figures/_plot_data.json ] && echo 1 || echo 0)
HAS_PREP_DATA=$(ls figures/prep_plot_data.py figures/prep_*.py 2>/dev/null | wc -l)
HAS_INCLUDES=$([ -f figures/latex_includes.tex ] && wc -c < figures/latex_includes.tex || echo 0)
TOTAL_FIG=$((HAS_PNG + HAS_PDF))
echo "  fig_*.png: $HAS_PNG, fig_*.pdf: $HAS_PDF, tikz_*.pdf: $HAS_TIKZ, fig_*.drawio: $HAS_DRAWIO"
echo "  gen_fig_*.py: $HAS_GEN_FIG, prep_*.py: $HAS_PREP_DATA, _plot_data.json: $HAS_PLOT_DATA"
echo "  latex_includes.tex: $HAS_INCLUDES bytes"
```

#### ⛔ FIGURE_MANIFEST 对账（必须跑）

```bash
echo ""
echo "=== FIGURE_MANIFEST 对账 ==="
PLAN_FILE=""
for f in PROBLEM_ANALYSIS.md PAPER_PLAN.md MODELING_REPORT.md; do
  [ -f "$f" ] && grep -q '<!-- BEGIN FIGURE_MANIFEST -->' "$f" && { PLAN_FILE="$f"; break; }
done

if [ -z "$PLAN_FILE" ]; then
  echo "⚠ 没找到 FIGURE_MANIFEST 区块 (PROBLEM_ANALYSIS.md 等都不含)"
  echo "  说明上游赛题分析阶段没产出图表清单 → 退而求其次, 用 fig_/tikz_ 数粗略对账"
  # 先数所有 fig_, 再减去 drawio/scene 类型
  ALL_FIG_REFS=$(grep -ohE 'fig_[a-zA-Z0-9_]+' PAPER_PLAN.md PROBLEM_ANALYSIS.md MODELING_REPORT.md 2>/dev/null | sort -u | wc -l)
  DRAWIO_REFS=$(grep -ohE 'fig_(roadmap|flow_q[0-9]+|pipeline|index_[a-zA-Z0-9_]+|gantt|network|framework|model_decision|scene)' PAPER_PLAN.md PROBLEM_ANALYSIS.md MODELING_REPORT.md 2>/dev/null | sort -u | wc -l)
  EXPECTED_DATA=$((ALL_FIG_REFS - DRAWIO_REFS))
  [ "$EXPECTED_DATA" -lt 0 ] && EXPECTED_DATA=0
  echo "  估算需要的数据图: $EXPECTED_DATA"
else
  echo "✅ 找到 FIGURE_MANIFEST: $PLAN_FILE"
  START=$(grep -n '<!-- BEGIN FIGURE_MANIFEST -->' "$PLAN_FILE" | head -1 | cut -d: -f1)
  END=$(grep -n '<!-- END FIGURE_MANIFEST -->' "$PLAN_FILE" | head -1 | cut -d: -f1)
  MANIFEST=$(sed -n "${START},${END}p" "$PLAN_FILE")

  # 提取每个 fig_xxx / tikz_xxx 名字
  ALL_MANIFEST_FIGS=$(echo "$MANIFEST" | grep -oE '^[[:space:]]*-[[:space:]]+(fig_[a-zA-Z0-9_]+|tikz_[a-zA-Z0-9_]+)' | sed 's/^[[:space:]]*-[[:space:]]*//')
  # ⛔ 拆成「数据图」与「流程/架构图(drawio/tikz)」两类。本步骤只对数据图硬对账，
  # drawio/tikz 类由 paper-figure-drawio / TikZ 子流程负责，缺它们不算本步骤失败(否则空转)。
  DRAWIO_PREFIXES='^(fig_arch|fig_flow|fig_roadmap|fig_pipeline|fig_framework|fig_er|fig_overview|fig_system|fig_module|fig_index|fig_hierarchy|fig_multiagent|fig_topology|fig_dataflow|fig_pkg|fig_class|fig_seq|fig_gantt|fig_network|fig_model_decision|fig_decision|fig_state|fig_uml|tikz_)'
  EXPECTED_FIGS=$(echo "$ALL_MANIFEST_FIGS" | grep -vE "$DRAWIO_PREFIXES")
  DRAWIO_FIGS=$(echo "$ALL_MANIFEST_FIGS" | grep -E "$DRAWIO_PREFIXES")
  echo "  规划数据图(本步骤负责)："
  echo "$EXPECTED_FIGS" | grep . | sed 's/^/    /'
  [ -n "$(echo "$DRAWIO_FIGS" | grep .)" ] && { echo "  流程/架构图(由 paper-figure-drawio 负责, 本步骤不检查)："; echo "$DRAWIO_FIGS" | grep . | sed 's/^/    /'; }

  # 逐条检查数据图产物是否存在 (任意一种格式都算: .png / .pdf / .drawio)
  MISSING_FIGS=""
  for name in $EXPECTED_FIGS; do
    if ls figures/${name}.png figures/${name}.pdf figures/${name}.drawio 2>/dev/null | head -1 | grep -q .; then
      :
    else
      MISSING_FIGS="$MISSING_FIGS $name"
    fi
  done
  MISSING_COUNT=$(echo "$MISSING_FIGS" | wc -w)
  TOTAL_EXPECTED=$(echo "$EXPECTED_FIGS" | grep -c . )
  echo ""
  echo "  数据图规划: $TOTAL_EXPECTED 张, 已产出: $((TOTAL_EXPECTED - MISSING_COUNT)) 张, 缺失: $MISSING_COUNT 张"
  if [ "$MISSING_COUNT" -gt 0 ]; then
    echo "  ❌ 缺失的数据图:"
    for m in $MISSING_FIGS; do echo "    - $m"; done
    echo ""
    echo "  ⛔ 必须把上面所有缺失的数据图都生成出来才能结束本步骤(流程/架构图不在此列)."
  else
    echo "  ✅ 数据图全部产出(流程/架构图归 paper-figure-drawio)"
  fi
fi
```

**根据扫描结果决定行动**：

| 状态 | 行动 |
|---|---|
| FIGURE_MANIFEST 对账显示 **MISSING_COUNT > 0** | ⛔⛔⛔ **逐张补齐**：每个缺失的 `fig_xxx` 必须按其在规划文档里的描述去生成。`fig_flow_q*` / `fig_roadmap` / `fig_pipeline` 等 drawio 类的 → 调 paper-figure-drawio；`tikz_*` → 调 TikZ 子流程；其余数据图 → Step 3 写 `gen_fig_xxx.py` 执行画图 |
| **`_plot_data.json` 存在 + `gen_fig_*.py` 计数为 0** | ⛔ **半完成状态！数据备好了但没画图！** 必须从 Step 3 开始为每组数据生成 `gen_fig_*.py` 真正画出 PNG/PDF。**禁止跳到 Step 9 自我安慰** |
| `gen_fig_*.py` 数 < `_plot_data.json` 里的数据组数 | **数据有 N 组但只画了 M 张**，必须补齐缺失的 gen_fig 脚本 |
| `TOTAL_FIG < PLAN_FIG_COUNT` 且 `gen_fig_*.py == 0` | **图全是 drawio 流程图，缺核心数据图**。检查 `figures/*.json` 数据，写 gen_fig 脚本补齐 |
| MANIFEST 全部产出 + latex_includes.tex 存在 | **跳到 Step 9 验证**，验证通过即完成 |
| latex_includes.tex 缺失但图都在 | **只生成 Step 6 的 latex_includes.tex** |
| 啥都没有 | 从 Step 1 开始 |

⛔⛔⛔ **半完成自检（最容易跳过）**：

如果你看到工作区有以下任一组合，**绝对不允许结束**：

1. FIGURE_MANIFEST 规划了 N 张但实际产出 < N → **少一张都不行**
2. `figures/_plot_data.json` 存在 但 `figures/gen_fig_*.py` 不存在 → 「备好食材没下锅」
3. `figures/*_results.json` ≥ 1 个 但 `figures/fig_*.png/pdf` 全是 drawio 流程图 → 「核心数据图没生成」
4. `prep_plot_data.py` 存在但 `gen_fig_*.py` 不存在 → 「数据准备完没真正画图」

碰到上述任意一种 → **跳到 Step 3 强制为每组数据生成 gen_fig 脚本，逐个执行产出 PNG/PDF**。
不允许靠"我已经有图了"来糊弄过去 — 数据图和流程图是两种东西，缺一不可。

**⛔ 参数密集型题目必跑（题面参数 ≥ 20 时）：图脚本审计**

```bash
# Step 4 末尾：检查图标签单位 / 图例与 facts 实体名匹配 / 图脚本数据来源
[ -f PROBLEM_FACTS.json ] && python3 _utils/facts_audit.py --stage figure 2>&1 | tee -a AUDIT_REPORT.md
FIG_RC=$?
if [ $FIG_RC -eq 1 ]; then
    echo "⛔ 图脚本审计失败：xlabel/ylabel 缺单位、图例与 facts 实体名不匹配、或脚本未从 JSON 读数据。请修正后重新跑。"
fi
```

**为什么 Step 4 也要审**：
- xlabel `"时间(s)"` 实际是分钟 → AI 长上下文里很容易蒙混过去
- 图例 `"无人机A"` 但 facts.weapons 里只有 `red_drone_1` → 实体名错位
- `plt.plot([0,5,10], [1.2,3.4,5.6])` 硬编码数据而不是读 JSON

⛔ **铁律**：
- **已有 `figures/fig_*.png/pdf` 不要重画**（覆盖会让审稿人看到的图变了）
- **已有的 `figures/TABLE_*.md/tex` 不要重写**（数据已固化）
- 只补缺失的图 / 表
- **drawio 流程图不能替代数据结果图**：竞赛论文要求技术路线图（drawio）+ 子问题求解流程图（drawio）+ **数据结果图（matplotlib gen_fig）**，三类都要有
- **规划了几张就必须画几张**：FIGURE_MANIFEST 是合同，少一张就是违约

### Step 1: Read paper structure + data discovery

1. Read the full style guide (color schemes + figure selection decision table + anti-patterns + DrawIO/TikZ color schemes — all in one file):
```bash
# ⛔ 直接 cat 整个 figure_style_guide.md (~50KB) 容易把 context 顶到上限触发 thrashing
# 改用 head 取前 1500 行的核心规则部分; 需要更细规则时再 grep 或 Read 工具按需读
(cat _utils/figure_style_guide.md 2>/dev/null || cat skills/shared-scripts/figure_style_guide.md) | head -1500
```
2. Scan recipe file headings to know what templates are available:
```bash
echo "=== Advanced ==="
(cat _utils/figure_recipes_advanced.md 2>/dev/null || cat skills/shared-scripts/figure_recipes_advanced.md 2>/dev/null) | grep '^## '
echo "=== Basic ==="
(cat _utils/figure_recipes_basic.md 2>/dev/null || cat skills/shared-scripts/figure_recipes_basic.md 2>/dev/null) | grep '^## '
echo "=== Academic ==="
(cat _utils/figure_recipes_academic.md 2>/dev/null || cat skills/shared-scripts/figure_recipes_academic.md 2>/dev/null) | grep '^## '
echo "=== Competition ==="
(cat _utils/figure_recipes_competition.md 2>/dev/null || cat skills/shared-scripts/figure_recipes_competition.md 2>/dev/null) | grep '^## '
echo "=== Empirical ==="
(cat _utils/figure_recipes_empirical.md 2>/dev/null || cat skills/shared-scripts/figure_recipes_empirical.md 2>/dev/null) | grep '^## '
echo "=== Basic (fallback only) ==="
(cat _utils/figure_recipes_basic.md 2>/dev/null || cat skills/shared-scripts/figure_recipes_basic.md 2>/dev/null) | grep '^## '
```
3. **⛔ MANDATORY: Extract the COMPLETE figure plan from planning docs.** Read ALL planning docs and extract every planned figure/table into a numbered checklist:
```bash
echo "=== Extracting figure plan (head -800 each, 防 thrashing) ==="
for plan in PAPER_PLAN.md PROBLEM_ANALYSIS.md TOPIC_PLAN.md MODELING_REPORT.md; do
    [ -f "$plan" ] || continue
    echo "--- $plan ---"
    head -800 "$plan"
done
# ⛔ 对完整规划用 Read 工具按需读, 不要 cat 全文.
# FIGURE_MANIFEST 区块的图列表可以用这个精确提取:
for plan in PROBLEM_ANALYSIS.md PAPER_PLAN.md MODELING_REPORT.md; do
    [ -f "$plan" ] || continue
    awk '/<!-- BEGIN FIGURE_MANIFEST -->/,/<!-- END FIGURE_MANIFEST -->/' "$plan" 2>/dev/null
done
```
After reading, output a **FIGURE PLAN CHECKLIST** like this (you MUST produce this before proceeding):
```
FIGURE PLAN CHECKLIST (from planning docs):
[ ] 1. fig_xxx — Descriptive stats distribution (Rain Cloud) — data: results.json
[ ] 2. fig_yyy — Model comparison radar (Radar) — data: results.json
[ ] 3. fig_zzz — Regression coefficient forest plot (Forest Plot) — data: results.json
[ ] 4. TABLE_desc — Descriptive statistics table — data: results.json
[ ] 5. TABLE_reg — Regression results table — data: results.json
[ ] 6. drawio_roadmap — Technical roadmap (DrawIO)
Total planned: 6 figures + 2 tables + 1 DrawIO
```
**Every item in the plan MUST appear in this checklist. If the plan says "12 figures", the checklist must have 12 entries.**

3.5. **⛔ JSON 数据完整性检查（确保数据能支撑所有图表）：**
```bash
echo "=== JSON 数据完整性检查 ==="
if [ -f figures/all_results.json ]; then
    python3 -c "
import json
with open('figures/all_results.json', 'r') as f:
    data = json.load(f)
# 列出所有顶层 key
keys = list(data.keys()) if isinstance(data, dict) else [f'[{i}]' for i in range(min(len(data), 10))]
print(f'JSON 顶层 key ({len(keys)} 个): {keys}')
# 检查是否有空值
def check_empty(obj, path=''):
    issues = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if v is None or v == '' or v == []:
                issues.append(f'{path}.{k} 为空')
            else:
                issues.extend(check_empty(v, f'{path}.{k}'))
    elif isinstance(obj, list) and len(obj) == 0:
        issues.append(f'{path} 为空列表')
    return issues
issues = check_empty(data)
if issues:
    print(f'⚠ 发现 {len(issues)} 个空值:')
    for i in issues[:5]:
        print(f'  - {i}')
else:
    print('✅ JSON 数据无空值')
" 2>/dev/null
else
    echo "⚠ figures/all_results.json 不存在，图表将缺少数据支撑"
fi
# 检查各子问题的结果文件
for f in figures/problem_*_results.json; do
    [ -f "$f" ] && echo "✅ $(basename $f) 存在" || true
done
```

4. Scan data files (`user_data/` > `figures/` > root). **⛔ 不要 `cat` 或 `print()` 整个 JSON 文件——大 JSON 会撑爆上下文。** 只用以下方式扫描：
```bash
ls -la figures/*.json 2>/dev/null
python3 -c "
import json, os
def summarize(v, depth=0):
    if isinstance(v, list):
        n = len(v)
        nulls = sum(1 for x in v if x is None)
        nums = [x for x in v if isinstance(x, (int,float)) and x is not None]
        if nums:
            return f'list[{n}] nulls={nulls} range=[{min(nums):.4g}, {max(nums):.4g}] sample={v[:3]}'
        elif v and isinstance(v[0], dict):
            return f'list[{n}] of dict, keys={list(v[0].keys())[:8]}'
        return f'list[{n}] sample={str(v[:3])[:100]}'
    elif isinstance(v, dict) and depth < 2:
        items = []
        for k2, v2 in list(v.items())[:6]:
            items.append(f'{k2}: {summarize(v2, depth+1)}')
        return 'dict{' + ', '.join(items) + '}'
    return f'{type(v).__name__}={str(v)[:60]}'

for f in sorted(os.listdir('figures')):
    if not f.endswith('.json'): continue
    sz = os.path.getsize(f'figures/{f}')
    with open(f'figures/{f}') as fh: d = json.load(fh)
    print(f'\n=== {f} ({sz//1024}KB) ===')
    if isinstance(d, dict):
        for k, v in list(d.items())[:10]:
            print(f'  {k}: {summarize(v)}')
    elif isinstance(d, list):
        print(f'  {summarize(d)}')
"
```

Every figure in the plan must be generated — the actual count can exceed the plan but not fall short.

<supplement_mode>
**Supplement mode**: if `figures/` already has ≥3 PDFs + `latex_includes.tex` from a previous step (e.g., experiment-bridge):
1. Compare existing PDFs against the FIGURE PLAN CHECKLIST
2. Check quality of each existing PDF (correct chart type, uses PALETTE, correct language labels)
3. **Regenerate** any figure that fails quality check
4. **Generate** any planned figure that doesn't exist yet
5. **Always generate** DrawIO architecture diagrams
6. **Always regenerate** `latex_includes.tex` to include ALL figures

**Normal mode** (no existing PDFs — this is the default for stats modeling since comp-code only outputs JSON):
Generate all figures from scratch using JSON data in `figures/*.json`.
</supplement_mode>

### Step 1.5: Generate GPT Image figures (non-data figures)

GPT Image 2 can generate high-quality scene diagrams, technical roadmaps, flowcharts, and architecture diagrams — far better than DrawIO.

**1. GPT Image 直接使用，无需预检查：**

API Key 已通过配置文件 `_utils/_gpt_image_config.json` 注入（用户在设置页面配置，后端自动写入）。
**直接调用即可。成功就用，失败 3 次后 DrawIO 兜底。不需要检测 Python 或检查环境变量。**

```bash
# Python 路径：VIBE_PYTHON 由后端注入，fallback 到系统 python
PYTHON="${VIBE_PYTHON:-$(command -v python3 2>/dev/null || command -v python 2>/dev/null || echo python)}"
GPT_IMG=1
echo "GPT_IMAGE: ready (Python=$PYTHON, config=_utils/_gpt_image_config.json)"
```

**2. Determine language:**
```bash
# Check paper language from planning docs（注意：comp_apmcm_zh 是中文赛项，必须先排除）
if grep -qi 'comp_apmcm_zh' CLAUDE.md 2>/dev/null; then
    GPTIMG_LANG="zh"
elif grep -qi 'MCM\|ICM\|APMCM\|comp_mcm\|comp_apmcm\|comp_certcup_en\|comp_shuwei_en' CLAUDE.md 2>/dev/null; then
    GPTIMG_LANG="en"
else
    GPTIMG_LANG="zh"
fi
echo "GPT Image language: $GPTIMG_LANG"
```

**3. Read ALL upstream documents to understand the FINAL methods and results:**
```bash
echo "=== Reading upstream docs for GPT Image prompt construction ==="
cat PROBLEM_ANALYSIS.md 2>/dev/null | head -500
cat MODELING_REPORT.md 2>/dev/null | head -500
cat RESULTS.md 2>/dev/null | head -200
```

**4. Read the GPT Image plan from PROBLEM_ANALYSIS.md:**
```bash
grep -A 30 'GPT Image' PROBLEM_ANALYSIS.md 2>/dev/null
```

**5. For each planned GPTIMG figure, construct a prompt and call the tool.**

**⛔ MANDATORY: 如果 PROBLEM_ANALYSIS.md 中规划了 GPTIMG 图（包含 "GPTIMG-" 或 "GPT Image" 字样），你必须尝试调用 gpt_image.py 生成。不允许跳过、不允许直接用 TikZ 替代。**

执行规则：
1. 检查规划中有几张 GPTIMG 图
2. 对每张图：调用 `python3 _utils/gpt_image.py`（工具内置 3 次重试）
3. 如果 3 次重试全部失败 → 记录到 `_gptimg_failed.txt` → 由 paper-figure-drawio 步骤自行选择最合适的替代方案（DrawIO 或 TikZ，根据图的内容自主判断）
4. **禁止行为：** 看到规划有 GPTIMG 但不调用就直接画替代图。必须先尝试 GPT Image，失败后才能降级

```bash
# ⛔ 强制检查：规划中是否有 GPTIMG 图
GPTIMG_PLAN_COUNT=$(grep -ci 'GPTIMG\|GPT.Image\|场景示意图' PROBLEM_ANALYSIS.md 2>/dev/null || echo 0)
echo "规划中的 GPT Image 图数量: $GPTIMG_PLAN_COUNT"
if [ "$GPTIMG_PLAN_COUNT" -gt 0 ]; then
    echo "⛔ 检测到 $GPTIMG_PLAN_COUNT 张 GPT Image 图规划 — 必须逐张尝试调用 gpt_image.py"
    echo "   失败 3 次后才允许降级（DrawIO 或 TikZ，自行判断哪个更合适）"
    echo "   ❌ 禁止跳过调用直接用替代方案"
fi
```

Claude must construct the prompt BASED ON THE FINAL methods/results from MODELING_REPORT.md (not the initial plan — methods may have changed during modeling/coding). Only write the core scene/layout/content description — language adaptation, style guidelines, and safety rules are automatically injected by the tool.

**⛔ 提示词越简洁，GPT Image 发挥越好。只描述场景和元素，不要写死颜色和布局细节。**

**GPT Image 只用于场景示意图（物理/工程类赛题的问题背景图）。技术路线图、求解流程图、模型架构图使用 DrawIO。**

<gpt_image_prompt_templates>

#### 场景示意图 (fig_scene.png)

仅适用于有具体物理/工程空间场景的赛题（光学、无人机、传感器、交通、热传导等）。
纯数据/统计类赛题不需要。

Claude 根据赛题自由构造 prompt，参考格式：

```
生成一张学术论文插图风格的{场景名}示意图。
{俯视/侧视/3D等距}视角。
画面包含：{元素1}、{元素2}、{元素3}。
用虚线箭头表示{某种关系/流向}，用不同颜色区分{不同类别}。
包含图例说明各颜色含义。
```

⛔ 约束：
- 不超过 6 个视觉元素
- 不生成真人面孔/肖像——需要人物时用抽象图标
- 必须包含图例框解释颜色含义
- 尺寸标注用数学变量（R, H, L）不用具体数字

</gpt_image_prompt_templates>

**6. Execute GPT Image calls (max 3 retries per figure, handled by the tool):**

```bash
GPTIMG_FAILED=""

# For each planned figure, call gpt_image.py
# Example (Claude generates the actual calls based on the plan):
$PYTHON _utils/gpt_image.py \
  --prompt "Generate a structured technical roadmap..." \
  --output figures/fig_roadmap.png \
  --lang $GPTIMG_LANG \
  --aspect-ratio 9:16 \
  --max-retries 3

if [ -f figures/fig_roadmap.pdf ]; then
    echo "✅ fig_roadmap generated via GPT Image 2"
else
    echo "❌ fig_roadmap FAILED after 3 retries — will use DrawIO fallback"
    GPTIMG_FAILED="$GPTIMG_FAILED fig_roadmap"
    GPTIMG_TOTAL_FAILURES=$((GPTIMG_TOTAL_FAILURES + 1))
fi

# Repeat for each GPTIMG figure...
# ⛔ 每张图独立重试 3 次（--max-retries 3），不要因为一张图失败就跳过后面的图
```

**7. Record failures for DrawIO fallback (persist to file for paper-figure-drawio step).**

```bash
# 统计结果
GPTIMG_TOTAL_PLANNED=$(echo "$GPTIMG_PLANNED" | wc -w)  # 计划生成的图数量
GPTIMG_TOTAL_FAILURES=${GPTIMG_TOTAL_FAILURES:-0}

echo "$GPTIMG_FAILED" > figures/_gptimg_failed.txt

# ⛔ 只有在 Python 不存在时才写 DISABLED
# 如果 Python 存在但 API Key 没配置或网络不通，所有图都会失败 → 写 ALL_FAILED（不是 DISABLED）
# 这样下一步 DrawIO 会为所有失败的图生成替代品
if [ "$GPT_IMG" -eq 0 ]; then
    # Python 不存在，完全跳过了 GPT Image
    echo "GPT_IMG_DISABLED" > figures/_gptimg_status.txt
elif [ -z "$GPTIMG_FAILED" ]; then
    # 所有图都成功了
    echo "ALL_SUCCESS" > figures/_gptimg_status.txt
elif [ "$GPTIMG_TOTAL_FAILURES" -ge "$GPTIMG_TOTAL_PLANNED" ] 2>/dev/null; then
    # 所有图都失败了（可能是 API Key 没配置或网络不通）
    echo "ALL_FAILED" > figures/_gptimg_status.txt
    echo "⚠ 所有 GPT Image 图都失败了，可能是 API Key 未配置或网络问题，DrawIO 将生成所有替代图"
else
    # 部分成功部分失败
    echo "SOME_FAILED" > figures/_gptimg_status.txt
fi
```

Status meanings:
- `ALL_SUCCESS` → all GPT Image figures generated, DrawIO only generates figures NOT in the GPT Image plan
- `SOME_FAILED` → DrawIO generates replacements ONLY for the failed figures
- `ALL_FAILED` → all attempts failed (API Key missing / network error), DrawIO generates ALL non-data figures
- `GPT_IMG_DISABLED` → Python not found, DrawIO generates ALL non-data figures

**8. GPT Image 生成后自检：**

对每张成功生成的 GPT Image 图，检查：
```bash
for img in figures/fig_scene*.pdf figures/fig_gptimg*.pdf; do
    [ -f "$img" ] || continue
    bn=$(basename "$img")
    sz=$(wc -c < "$img")
    echo "=== $bn ($sz bytes) ==="
    # 文件大小检查：GPT Image 生成的 PDF 通常 > 50KB
    if [ "$sz" -lt 50000 ]; then
        echo "❌ $bn 文件过小 ($sz bytes)，可能是空白或损坏"
    else
        echo "✅ $bn 文件大小正常"
    fi
done
```

⛔ GPT Image 无法做内容级自检（不能读取图片内容），但必须确保：
- PDF 文件存在且 > 50KB
- 如果生成的是 PNG，确认已自动转换为 PDF（LaTeX 需要 PDF）
- 失败的图记录到 GPTIMG_FAILED，DrawIO 子阶段会自动兜底

### Step 2: Figure type decisions

Browse the recipe library (97 total across 5 files) and the `<figure_selection_guide>` decision table from the style guide. For each planned figure:

1. Identify the data characteristic (e.g., "3 methods × 4 metrics comparison")
2. Browse ALL available recipe types — don't default to the same few charts every time
3. Pick the type that best fits the data AND looks visually distinct from other figures in this paper
4. Ensure visual variety: do not use the same chart type more than 2 times in one paper. Mix basic, advanced, competition, and empirical recipes
5. Read the full code example from the matched recipe file
6. Select the color palette based on paper domain

**⛔ Do NOT always default to grouped bar / lollipop / line chart.** The recipe library has 97 chart types — use the variety. For any data shape, there are usually 3-5 suitable types. Pick the one that's most visually interesting AND hasn't been used yet in this paper.

Reference `_utils/figure_exemplars.md` for figure distribution examples by paper type. Decide count and placement autonomously.

### Step 2.5: Detailed figure type planning (variety check)

For each planned figure, create a Figure Type Audit Table. The "Chosen Type" should be your autonomous choice from the full recipe library — the examples below are just illustrations, not fixed recommendations:

```
| # | Data Description | Chosen Type | Why | Recipe Ref |
|---|-----------------|-------------|-----|------------|
| 1 | 4 methods × 3 metrics | (your choice from library) | (your reasoning) | (recipe #) |
| 2 | ablation results | (your choice) | | |
| 3 | feature importance | (your choice) | | |
| ... | ... | ... | ... | ... |
```

**Variety check**: count unique chart types in the table. If < 4 unique types for a paper with ≥6 figures, go back and swap some for alternatives from the recipe library. Browse recipe headings again if needed.

### Step 3: Generate figure scripts

One `gen_fig_xxx.py` script per figure, executed from workspace root. Each script starts with `_utils` initialization and `setup_style()` call.

**MANDATORY**: Before writing each script, you MUST extract the matched recipe code using `get_recipe.py`. Copy the recipe code as the starting point, then adapt it to the actual data. Do NOT write figure scripts from scratch — the recipes contain critical styling details (gradient fills, KDE backgrounds, annotation boxes, layered visuals) that you will miss if you write from memory.

**⛔ Subfigure 组合图实现（当 FIGURE_MANIFEST 标了 `[2-panel]` / `[4-panel]`）**：

读 MANIFEST 时识别 panel 标注，生成的 PDF 内部已包含多 panel：

```python
# 例：fig_q2_residual_diag [4-panel]  → 用 plt.subplots(2, 2)
fig, axes = plt.subplots(2, 2, figsize=(10, 8))
fig.tight_layout(pad=1.2)
# 每个 subplot 加 (a)(b)(c)(d) 标签（短标签紧贴左上角）
for i, ax in enumerate(axes.flat):
    ax.set_title(f'({chr(97+i)})', fontsize=11, fontweight='bold', loc='left', pad=3)
# (a) Q-Q 图
axes[0,0].scatter(theoretical, sample, ...); axes[0,0].set_xlabel('理论分位数')
# (b) 残差-拟合
axes[0,1].scatter(fitted, resid, ...)
# (c) 直方图
axes[1,0].hist(resid, bins=30)
# (d) 残差-时间
axes[1,1].plot(time, resid)
save_fig(fig, 'figures/fig_q2_residual_diag.pdf')

# 例：fig_q3_method_cmp [2-panel]  → 用 plt.subplots(1, 2)
fig, axes = plt.subplots(1, 2, figsize=(11, 4.2))
axes[0].plot(iters, ga_obj, label='GA'); axes[0].set_title('(a)', loc='left')
axes[1].bar(['GA','SA'], [42.3, 67.8]);    axes[1].set_title('(b)', loc='left')
fig.tight_layout()
save_fig(fig, 'figures/fig_q3_method_cmp.pdf')
```

**关键点**：
- multi-panel 在**单个 PDF 内**实现（不是写两张 PDF），下游 LaTeX 用一个 `\includegraphics` 引用即可
- panel 数量 ≤ 4，宽度 figsize 第一维：2-panel 用 11，4-panel 用 10-12（保证每 panel 实际显示宽度 ≥ 0.45\textwidth）
- 每 panel 内部小标题 `(a) (b)` 短标签，用 `loc='left'` 紧贴左上
- 详细描述（如"Q-Q 图检验正态性"）放主 figure 的 LaTeX `\caption{}`，不要塞进 ax 标题
- save_fig 文件名仍按 MANIFEST 名（`fig_xxx.pdf` 单文件），LaTeX 引用时整张图作为 `\includegraphics`

```bash
# Example: if the plan says "fig_xxx — 堆叠面积图 (basic #8)", extract recipe first:
python3 _utils/get_recipe.py basic 8
# Example: if the plan says "fig_yyy — 龙卷风图 (competition #2)":
python3 _utils/get_recipe.py competition 2
# Then copy the output code, adapt to actual data, save as figures/gen_fig_xxx.py
```

**⛔ For EVERY figure script you write, the workflow is:**
1. Read the plan entry: `fig_xxx — 图表类型 (category #N)`
2. Extract recipe: `python3 _utils/get_recipe.py category N`
3. Copy the recipe code as starting point
4. Replace demo data with actual data from `figures/*.json`
5. Save as `figures/gen_fig_xxx.py`

**Skip this = ugly figures with wrong colors and no styling. The quality gate WILL reject them.**

If you skip this step and generate a figure with matplotlib default blue, no gradient fills, or no annotations, the figure will be rejected in Step 4 self-check.

<script_template>
**Copy this EXACTLY as the first lines of every gen_fig_*.py script. Output extension：默认 `.pdf`（LaTeX 模式）；如果 CLAUDE.md 末尾包含「⛔ 输出格式：仅 PNG」（Word/docx 模式）就改成 `.png`：**

```python
import os, sys, shutil
os.makedirs('_utils', exist_ok=True)
for src in ['plot_utils.py']:
    for search in ['skills/shared-scripts', '../skills/shared-scripts']:
        p = os.path.join(search, src)
        if os.path.isfile(p):
            shutil.copy2(p, f'_utils/{src}')  # copies .py file, NOT .pdf
            break
sys.path.insert(0, '.')  # plain dot, NOT '.pdf'
from _utils.plot_utils import setup_style, save_fig, PALETTE
setup_style()  # defaults to Soft palette; alternatives: tableau/npg/nejm/science/colorblind

# ... figure generation code ...
# Read data from JSON/CSV, never hardcode numbers
# NEVER use cmap='RdYlGn' — use 'coolwarm' or 'YlOrRd' instead. Do NOT use 'RdBu_r' (too dark)
# No plt.title() — captions go in LaTeX only
# 默认 LaTeX 模式：save_fig(fig, 'figures/fig_xxx.pdf')
# Word/docx 模式：save_fig(fig, 'figures/fig_xxx.png')  # 自动 350 DPI 防中文糊
```
</script_template>

**⛔ 地图类图表（中国省级热力图）环境说明：**
- 环境已预装 `geopandas`，直接 `import geopandas as gpd` 即可
- GeoJSON 文件：`_utils/china_provinces.geojson`（首次运行自动从 `skills/shared-scripts/` 复制或从阿里云 DataV 下载）
- **⛔ 绝对不要用散点图代替地图！** 必须用 `gdf.plot()` 画省份多边形轮廓
- 如果 geopandas 导入失败，用纯 matplotlib 方案：从 GeoJSON 解析坐标，用 `matplotlib.patches.Polygon` 手动画省份轮廓（参考 figure_recipes_competition.md #7 方案 B）

**⛔ figsize 硬限制（所有图表必须遵守）：**
- `figsize` 的 height 不能超过 8 英寸（约 20cm）。超过会导致图占满整页，前一页只剩一句引导文字
- 数据条目多（20+ 个类别的柱状图/条形图）：只展示 Top 15-20，其余放附录表格。或者用 `figsize=(7, 6)` + `fontsize=7` 缩小
- **条目超过 15 个时优先换图表类型**：横向柱状图 → 棒棒糖图（lollipop，更紧凑）；排名柱状图 → 表格（LaTeX 三线表更省空间）；分类对比 → 雷达图或热力图（一张图展示所有维度）
- 横向柱状图（barh）条目超过 15 个时，必须限制 `figsize=(7, max(4, n*0.25))`，且 height 上限 8
- 热力图/混淆矩阵超过 10×10 时，用 `figsize=(8, 7)` + `fontsize=7`
- **验证**：生成后检查 PDF 文件尺寸，如果高度 > 25cm 必须缩小重新生成

### Step 4: Self-check + execute

⛔⛔ **MANDATORY: run figure_check.sh BEFORE executing any gen_fig script.** Exit code 0 is required to proceed. Non-zero means CRITICAL violations exist (missing `setup_style`, hardcoded colors, `#1f77b4` matplotlib-default blue, etc.) — fix them and re-run until exit code is 0.

```bash
bash _utils/figure_check.sh 2>/dev/null || bash skills/shared-scripts/figure_check.sh
RC=$?
if [ "$RC" -ne 0 ]; then
    echo "❌ figure_check.sh failed (RC=$RC) — $RC CRITICAL violations must be fixed BEFORE running gen_fig scripts"
    echo "   Common fixes listed below; apply with Edit tool, then re-run figure_check.sh"
    # 不要 exit — 让 AI 继续读后续 fix_patterns 并修复
fi
```

<fix_patterns>
If violations found (especially CRITICAL), fix and re-check before executing:
- CRITICAL missing `setup_style` → add initialization code from script_template above
- Hardcoded color (`color='#XXXXXX'` not from PALETTE/COLORS) → `PALETTE[n]` or `COLORS['up'/'down'/'grid'/'text']`
- Named CSS color (`color='blue'`, `'red'`, `'green'`) → `PALETTE[n]`
- matplotlib default blue `#1f77b4` (and the rest of tab10) → use `PALETTE` (just calling `setup_style()` auto-applies it to all subsequent `ax.bar/plot/scatter` without `color=` arg)
- `plt.title()` → remove (caption in LaTeX only)
- `ax.grid()` → remove (setup_style handles grid)
- `RdYlGn` or `RdYlGn_r` colormap → use `coolwarm` (for diverging) or `YlOrRd` (for sequential). Do NOT use `RdBu_r` (too dark)
- Empty value placeholders → read from data files
</fix_patterns>

**After fixing, re-run figure_check.sh until RC=0. Only then execute the figure scripts.**

**Execute each script ONE BY ONE (not batch). If a script fails, fix it immediately before moving to the next:**

```bash
PYTHON=$(command -v python3 2>/dev/null || command -v python 2>/dev/null)
FAILED=0
for script in figures/gen_fig*.py; do
    [ -f "$script" ] || continue
    bn=$(basename "$script" .py)
    echo "=========================================="
    echo "Running: $script"
    echo "=========================================="
    $PYTHON "$script" 2>&1
    EXIT_CODE=$?

    # Check if PDF was generated
    expected_pdf="figures/${bn#gen_}.pdf"
    if [ $EXIT_CODE -ne 0 ] || [ ! -f "$expected_pdf" ]; then
        # Try alternate naming
        any_new=$(find figures/ -name "*.pdf" -newer "$script" 2>/dev/null | head -1)
        if [ -z "$any_new" ]; then
            echo "❌ FAILED: $script (exit=$EXIT_CODE) — NO PDF generated"
            echo "   → Read the error above, fix the script, and re-run it"
            FAILED=$((FAILED+1))
        else
            echo "✅ OK: $script → $any_new"
        fi
    else
        echo "✅ OK: $script → $expected_pdf"
    fi
done
[ -d "figures/figures" ] && mv figures/figures/*.pdf figures/ 2>/dev/null
echo ""
echo "=== Summary: $FAILED scripts failed ==="
```

**If FAILED > 0, you MUST go back and fix each failed script:**
1. Read the error output (ImportError? FileNotFoundError? data issue?)
2. Fix the script (add missing import, fix data path, etc.)
3. Re-run ONLY the failed script: `$PYTHON figures/gen_fig_xxx.py`
4. Verify the PDF exists: `ls -la figures/fig_xxx.pdf`
5. Repeat until all scripts produce PDFs

**Do NOT proceed to Step 5 until every gen_fig_*.py has produced its PDF.**

### Step 5: Generate tables (LaTeX OR Markdown — pick by output mode)

**⛔ FIRST: detect output format mode**

```bash
echo "=== 检测输出格式 ==="
# CLAUDE.md 顶部「## 参数」段会列 output_format
OUTPUT_FORMAT=$(grep -E '^- output_format:' CLAUDE.md 2>/dev/null | sed -E 's/.*: *//' | head -1 | tr -d '[:space:]')
OUTPUT_FORMAT=${OUTPUT_FORMAT:-pdf}
echo "Output format: $OUTPUT_FORMAT"

# 学术写作四大模板始终是 docx 模式（即使 output_format 没明写）
TEMPLATE=$(grep -E '^- template:' CLAUDE.md 2>/dev/null | sed -E 's/.*: *//' | head -1 | tr -d '[:space:]')
case "$TEMPLATE" in
    thesis_proposal|literature_review|course_paper|course_report)
        OUTPUT_FORMAT=docx
        echo "学术写作模板，强制 docx 模式"
        ;;
esac

if [ "$OUTPUT_FORMAT" = "docx" ]; then
    TABLE_EXT="md"
    echo "⛔ Word/DOCX 模式：表格输出 .md（Markdown 三线表）"
else
    TABLE_EXT="tex"
    echo "PDF 模式：表格输出 .tex（booktabs 三线表）"
fi
echo "TABLE_EXT=$TABLE_EXT (将用于 figures/TABLE_*.${TABLE_EXT})"
```

**⛔ At minimum: main results comparison table + descriptive statistics table.**
- PDF 模式 → Save as `figures/TABLE_xxx.tex`（booktabs 三线表）
- Word/DOCX 模式 → Save as `figures/TABLE_xxx.md`（Markdown 三线表）

**⛔ For Chinese papers: table captions and column headers MUST be in Chinese.** Check TOPIC_PLAN.md or PROBLEM_ANALYSIS.md to determine paper language. If Chinese (stats modeling / math modeling competition), all `\caption{}` and column headers must use Chinese.

**⛔ DOCX 模式下 Markdown 三线表的标准格式（必须遵守）：**

```markdown
**表 1：模型性能对比**

| 模型 | RMSE | MAE | R² |
|---|---|---|---|
| LSTM | 0.023 | 0.018 | 0.94 |
| Transformer | 0.019 | 0.015 | 0.96 |
| XGBoost | 0.021 | 0.017 | 0.95 |

> 注：所有指标基于测试集；最优值已加粗。

<!-- label: tab:model_perf -->
```

铁律：
- 表标题：`**表 X：标题**`（不是 `\caption{}`）
- 表头单独一行 `| h1 | h2 |`，**接下来必须有分隔行** `|---|---|`
- 每行 `|` 数量必须一致（列数对齐）
- 单元格里的 `|` 必须转义为 `\|`
- 表注：`> 注：xxx`（引用块）
- ⛔ **不要**在 .md 里写 `\begin{table}` / `\begin{tabular}` / `\toprule` / `\midrule` / `\bottomrule`
- ⛔ **不要**输出 .tex 文件（Word 模式根本不读）

**调用 stats_utils 时按后缀输出对应格式：**

```python
from _utils.stats_utils import regression_table, descriptive_table

# 自动按后缀选格式（推荐）
ext = "md" if output_format == "docx" else "tex"
regression_table(results, ['OLS', 'Logit'],
                 output=f'figures/TABLE_regression.{ext}',
                 caption='回归结果')
descriptive_table(df, output=f'figures/TABLE_descriptive.{ext}')
```

<table_sizing>
**LaTeX 模式（.tex）：**
- Narrow tables (≤4 columns): do not use `\resizebox` — it stretches text to full width, font becomes huge
- Wide tables (≥6 columns): wrap with `\resizebox{\textwidth}{!}{...}` to prevent overflow
- Use three-line style (booktabs): `\toprule`, `\midrule`, `\bottomrule`
- **⛔ Tall tables (>30 rows or multirow causing >35 visual rows)**: use `longtable` environment or split into multiple smaller tables. A single `tabular` that exceeds one page will be silently truncated.
- **⛔ Hyperparameter/config tables**: if models have very different parameter counts (e.g., Linear Reg 2 params vs LSTM 9 params), split into separate small tables per model or use `longtable`. Do not cram all models into one huge tabular.

**Markdown 模式（.md）：**
- 列数 ≤ 8（Word 渲染列数过多会挤压）；超过 8 列必须横向拆分
- 数据行 ≤ 25（超过 25 行的表格在 Word 里跨页效果差）；超过的拆为「正文摘要表 + 附录完整表」
- 单元格内不要换行（`<br>` Word 不一定渲染）
- 不要嵌套表格（Markdown 不支持）
- 数值精度统一：百分比保留 2 位小数（94.72%），系数保留 3-4 位（0.0234）
</table_sizing>

### Step 6: Generate LaTeX include snippets

Save to `figures/latex_includes.tex`. Use `[H]` float specifier (requires `\usepackage{float}`).

**⛔ Captions must match paper language.** Check TOPIC_PLAN.md or PROBLEM_ANALYSIS.md:
- Chinese papers (stats modeling / math competition): `\caption{模型性能对比雷达图}` — Chinese caption
- English papers (MCM/ICM/APMCM): `\caption{Model Performance Comparison}` — English caption

**⛔ Axis labels in gen_fig_*.py must also match paper language:**
- Chinese: `ax.set_xlabel('迭代次数')`, `ax.set_ylabel('目标函数值')`, `label='本文算法'`
- English: `ax.set_xlabel('Iterations')`, `ax.set_ylabel('Objective Value')`, `label='Ours'`

### Step 8: Quality check

<quality_checklist>
- No in-figure title (captions in LaTeX only)
- Font ≥10pt
- Grayscale-distinguishable
- Legend does not obscure data
- Axes have units
- PDF vector output
- All values populated (no empty placeholders)
- Text does not obscure data points
- Numbers consistent with paper body / RESULTS.md
- ⛔ **完整性（防残图）**：y 轴必须有刻度数字（不要清空 y 轴）；隐藏 x 刻度时必须直接标注数据（bar_label/text）；每个 `fill_between`/置信带必须同时画出主曲线（不能只剩一块色块）；非热力图不要 `set_frame_on(False)`；多子图每个子图都要有可见的轴+标签。**打开每张图确认它不是漂浮的色块，否则修正重画。**
</quality_checklist>

**⛔ MANDATORY: Figure intelligent self-review (review each figure after all are generated):**

Review each generated figure against its script code. Answer the following for each. If any ❌, regenerate that figure.

```
=== Per-figure review ===
For each fig_xxx.pdf, answer:

1. [Type match] Is this chart type the best choice for this data?
   - Method comparison (≤4 methods) → Grouped bar, not lollipop
   - Single-dim ranking/count → Horizontal bar (sorted + gradient color) or Pareto. Do NOT use vertical multi-color bars (random color per bar without grouping = visual noise, looks amateurish)
   - Method ranking (≥5 methods) → Horizontal bar preferred; Lollipop OK but must have gradient bg + highlight row + reference line
   - ⛔ Lollipop: if only plain stem+dot with no decoration, visual effect is poor — must follow adv #1 recipe with gradient bg + #1 highlight + median reference line
   - Time series trend → Line chart, not bar chart
   - Distribution comparison → Rain Cloud or box plot, not bar chart
   - Correlation matrix → Heatmap, not scatter matrix
   - Composition/proportion → Stacked bar or donut chart
   - If unsure, refer to _utils/figure_style_guide.md decision table

2. [Visual quality] Does the figure look professional and clear?
   - Enough spacing between data points/bars? (not crammed together)
   - Uses PALETTE colors, not matplotlib default blue?
   - Has light-fill + solid-border premium look? (not plain solid blocks + white edges)
   - Annotation text readable? (no overlap, not too small)
   - Heatmap: text color auto-adapts to background? (white on dark cells, black on light cells)

3. [Occlusion check] Are there any overlap/clipping issues?
   - Labels overlapping each other? → use smart_labels() or adjust offset/fontsize
   - Labels overlapping data elements (bars/lines/dots)? → move labels above/below or add white bbox background
   - Legend covering data points? → move legend to empty area (loc='upper left' if data is on the right, etc.) or place outside plot
   - Axis tick labels cut off or overlapping? → rotate labels, reduce fontsize, or increase figure margins
   - Data points clipped at plot edges? → expand xlim/ylim by 5-10%
   - Colorbar overlapping the plot area? → adjust pad/shrink parameters
   - For multi-panel figures: subplot titles overlapping adjacent subplot content? → increase hspace/wspace

3. [Recipe usage] Is each figure based on recipe code?
   - Does the script call setup_style() + PALETTE?
   - Has premium elements from recipe? (gradient fills, KDE backgrounds, annotation boxes, smart_labels, etc.)
   - If plain matplotlib default style (blue bars, no annotations, no fills), must rewrite using recipe

4. [Information value] Does the figure convey meaningful information?
   - Has reference lines / annotation boxes / significance markers?
   - Are data differences visible? (if all bars are nearly the same height, the figure has no information value)
   - Is there a "so what" — what conclusion can the reader draw?

5. [Diversity] Are chart types diverse across the paper?
   - Same chart type appearing ≥3 times? If so, swap one
   - All bar charts? Mix at least 3+ different types
   - Lollipop: if used, must have premium visual effects (gradient background, #1 highlight row, median reference line + annotation box). Plain stem+dot = reject and redo
```

If any figure has wrong type or poor visual quality, delete and regenerate.

### Step 9: Count verification (MUST match plan — checklist reconciliation)

**⛔ 先重新读规划文档，提取图表清单（上下文可能已截断，必须重新读）：**
```bash
echo "=== 重新读取规划文档中的图表清单 ==="
for plan in PROBLEM_ANALYSIS.md TOPIC_PLAN.md PAPER_PLAN.md MODELING_REPORT.md; do
    [ -f "$plan" ] || continue
    echo "--- $plan 中的图表规划 ---"
    grep -E 'fig_|TABLE_|DrawIO|TikZ|GPTIMG|数据图|图表' "$plan" | head -30
done
echo ""
echo "=== 已生成的 PDF 文件 ==="
ls -la figures/fig_*.pdf 2>/dev/null
echo ""
echo "=== 已生成的 TABLE 文件 ==="
ls -la figures/TABLE_*.tex figures/TABLE_*.md 2>/dev/null
```

Go back to the FIGURE PLAN CHECKLIST from Step 1. For each item, check if the corresponding file exists:

```bash
echo "=== FIGURE PLAN CHECKLIST RECONCILIATION ==="
echo ""
echo "PDF figures generated:"
ls -1 figures/*.pdf 2>/dev/null
echo ""
echo "Tables generated:"
ls -1 figures/TABLE_*.tex figures/TABLE_*.md 2>/dev/null
echo ""
echo "DrawIO diagrams:"
ls -1 figures/*.drawio 2>/dev/null && echo "YES" || echo "NO"
echo ""
echo "=== Planned figures (from planning docs) ==="
for plan in PAPER_PLAN.md PROBLEM_ANALYSIS.md TOPIC_PLAN.md MODELING_REPORT.md; do
    [ -f "$plan" ] && echo "--- $plan ---" && grep -i 'fig\|图\|table\|表\|chart\|plot\|heatmap\|radar\|DrawIO\|drawio\|TikZ\|tikz' "$plan" | head -30
done
```

**⛔ MANDATORY: Update the checklist with actual status:**
```
FIGURE PLAN CHECKLIST (reconciliation):
[✅] 1. fig_desc_stats — 描述性统计分布图 → figures/fig_desc_stats.pdf (exists, 45KB)
[✅] 2. fig_radar — 模型对比雷达图 → figures/fig_radar.pdf (exists, 38KB)
[❌] 3. fig_forest — 回归系数森林图 → MISSING — need to generate
[✅] 4. TABLE_desc — 描述性统计表 → figures/TABLE_desc.{tex|md}（按 OUTPUT_FORMAT 决定）(exists)
[❌] 5. TABLE_reg — 回归结果表 → MISSING — need to generate
[✅] 6. drawio_roadmap — 技术路线图 → figures/fig_roadmap.drawio + figures/fig_roadmap.pdf (exists)
Result: 4/6 complete, 2 MISSING
```

**If ANY item is marked ❌:**
1. Go back to Step 3 and generate scripts for the missing figures
2. Execute them (Step 4)
3. Re-run this Step 9 reconciliation
4. **Repeat until ALL items are ✅**
5. **⛔ 如果某张图反复失败（同一工具 3 轮都不行），启用跨工具兜底：**
   - DrawIO 失败 → 降级到 TikZ（简化版）
   - TikZ 失败 → 降级到 DrawIO（去掉公式，用文字代替）
   - GPT Image 失败 → 降级到 DrawIO（已有机制）
   - Matplotlib 失败 → 简化图表类型（如雷达图失败→换分组柱状图）

**Do NOT finish until every planned item exists as a file. The plan is the contract.**

### Step 10: ⛔ FINAL QUALITY GATE

```bash
echo "=========================================="
echo "  FIGURE GENERATION QUALITY GATE"
echo "=========================================="
GATE_FAIL=0

# 1. All gen_fig scripts produced PDFs
SCRIPTS=$(ls figures/gen_fig*.py 2>/dev/null | wc -l)
PDFS=$(ls figures/fig_*.pdf 2>/dev/null | wc -l)
[ "$PDFS" -ge "$SCRIPTS" ] && echo "✅ All scripts produced PDFs ($PDFS/$SCRIPTS)" || { echo "❌ $((SCRIPTS-PDFS)) scripts failed to produce PDFs"; GATE_FAIL=$((GATE_FAIL+1)); }

# 2. latex_includes.tex exists and non-empty
[ -s figures/latex_includes.tex ] && echo "✅ latex_includes.tex exists" || { echo "❌ latex_includes.tex missing or empty"; GATE_FAIL=$((GATE_FAIL+1)); }

# 2.5 ⛔ 用户在「高级选项」指定的 MIN_FIGURES 数量自检（数据图最低数量硬目标）
#     只在用户明确指定 MIN_FIGURES > 0 时生效；其他情况跳过保持原本行为
source .env_skill 2>/dev/null || true
if [ -n "$MIN_FIGURES" ] && [ "$MIN_FIGURES" -gt 0 ] 2>/dev/null; then
    DATA_FIGS=$(ls figures/fig_*.png figures/fig_*.pdf 2>/dev/null | wc -l)
    if [ "$DATA_FIGS" -lt "$MIN_FIGURES" ]; then
        echo "❌ 用户在前端「高级选项」要求数据图 ≥ $MIN_FIGURES 张，但实际产出 $DATA_FIGS 张"
        echo "   必须扩展：补充缺失的 gen_fig_*.py 脚本生成更多图，或检查 FIGURE_MANIFEST 是否漏了"
        GATE_FAIL=$((GATE_FAIL+1))
    else
        echo "✅ 数据图数量达标 ($DATA_FIGS / 用户要求 $MIN_FIGURES)"
    fi
fi

# 3. DrawIO diagrams (if planned)
if grep -qi 'drawio\|DrawIO\|架构图\|技术路线\|roadmap\|framework\|流程图' PAPER_PLAN.md TOPIC_PLAN.md PROBLEM_ANALYSIS.md 2>/dev/null; then
    # DrawIO/TikZ 检查已移至 paper-figure-drawio 步骤，此处跳过
    DRAWIO_COUNT=$(ls figures/*.drawio 2>/dev/null | wc -l)
    [ "$DRAWIO_COUNT" -gt 0 ] && echo "  (DrawIO: $DRAWIO_COUNT files — will be validated by paper-figure-drawio step)" || echo "  (no DrawIO yet — will be generated by paper-figure-drawio step)"
fi

# 4. Figure check script passes
bash _utils/figure_check.sh 2>/dev/null || bash skills/shared-scripts/figure_check.sh 2>/dev/null
FC_EXIT=$?
[ "$FC_EXIT" -eq 0 ] && echo "✅ Figure check passed" || { echo "❌ Figure check failed (exit=$FC_EXIT) — fix color/style issues"; GATE_FAIL=$((GATE_FAIL+1)); }

# 4.1 图例/标注遮挡检查（代码层面）
echo "--- 图例遮挡风险检查 ---"
for script in figures/gen_fig*.py; do
    [ -f "$script" ] || continue
    bn=$(basename "$script")
    # 检查是否硬编码了 loc='upper right'（收敛曲线等场景容易遮挡）
    if grep -q "loc='upper right'" "$script" 2>/dev/null; then
        echo "  ⚠ $bn: 图例硬编码 loc='upper right' — 如果数据在右上角会遮挡，建议改为 loc='best'"
    fi
    # 检查是否有 annotate 和 legend 在同一区域
    HAS_ANNOTATE=$(grep -c 'ax.annotate\|ax.text' "$script" 2>/dev/null || echo 0)
    HAS_LEGEND=$(grep -c 'ax.legend' "$script" 2>/dev/null || echo 0)
    if [ "$HAS_ANNOTATE" -gt 0 ] && [ "$HAS_LEGEND" -gt 0 ]; then
        if ! grep -q "bbox_to_anchor\|loc='best'" "$script" 2>/dev/null; then
            echo "  ⚠ $bn: 同时有标注和图例但未用 loc='best' 或 bbox_to_anchor — 可能遮挡"
        fi
    fi
    # 检查 annotate 的 xytext 是否用硬编码偏移（容易超出图表边界）
    # plot_utils._clamp_texts_to_axes 会在 savefig 时自动裁剪，但最好从源头避免
    if [ "$HAS_ANNOTATE" -gt 0 ]; then
        HARDCODED_OFFSET=$(grep -cP 'xytext=\([^)]*\+\s*\d' "$script" 2>/dev/null || echo 0)
        if [ "$HARDCODED_OFFSET" -gt 2 ]; then
            echo "  ⚠ $bn: $HARDCODED_OFFSET 处 annotate 用硬编码偏移 — 数据靠近边缘时标注会超出图表"
            echo "    建议：用 textcoords='offset points' 或确保 xytext 在 ax.get_xlim()/get_ylim() 范围内"
        fi
    fi
done

# 4.5 TikZ/DrawIO — handled by paper-figure-drawio step, skip here
echo "  (TikZ/DrawIO diagrams will be generated and validated by the next step: paper-figure-drawio)"

# 4.6 GPT Image figures (if planned)
GPTIMG_PLANNED=$(grep -ci 'GPTIMG\|GPT.Image\|场景示意' PROBLEM_ANALYSIS.md 2>/dev/null || echo 0)
if [ "$GPTIMG_PLANNED" -gt 0 ]; then
    GPTIMG_PDF=$(ls figures/fig_scene*.pdf figures/fig_gptimg*.pdf 2>/dev/null | wc -l)
    if [ "$GPTIMG_PDF" -gt 0 ]; then
        echo "✅ GPT Image figures: $GPTIMG_PDF PDFs"
    else
        # Check if DrawIO fallback was used
        echo "  GPT Image: no PDFs (may have used DrawIO fallback — check GPTIMG_FAILED)"
    fi
else
    echo "  (no GPT Image planned)"
fi

# 5. Plan reconciliation count
PLAN_FIGS=0
for plan in PAPER_PLAN.md TOPIC_PLAN.md PROBLEM_ANALYSIS.md; do
    [ -f "$plan" ] || continue
    pf=$(grep -ci 'fig_\|图.*：\|figure.*:\|TABLE_' "$plan" 2>/dev/null || echo 0)
    [ "$pf" -gt "$PLAN_FIGS" ] && PLAN_FIGS=$pf
done
ACTUAL_TOTAL=$((PDFS + $(ls figures/TABLE_*.tex figures/TABLE_*.md 2>/dev/null | wc -l)))
if [ "$PLAN_FIGS" -gt 0 ]; then
    [ "$ACTUAL_TOTAL" -ge "$PLAN_FIGS" ] && echo "✅ Output count: $ACTUAL_TOTAL (plan: ~$PLAN_FIGS)" || { echo "❌ Only $ACTUAL_TOTAL outputs (plan: ~$PLAN_FIGS)"; GATE_FAIL=$((GATE_FAIL+1)); }
else
    echo "  Output count: $ACTUAL_TOTAL (no plan to compare)"
fi

# 6. No empty/tiny PDFs
TINY=0
HUGE=0
for pdf in figures/fig_*.pdf; do
    [ -f "$pdf" ] || continue
    sz=$(wc -c < "$pdf")
    [ "$sz" -lt 5000 ] && { echo "  ❌ $(basename $pdf) is only $sz bytes — likely broken"; TINY=$((TINY+1)); }
done
# Check for oversized PDFs (DrawIO/TikZ/GPT Image figures that might be too tall)
for pdf in figures/fig_roadmap.pdf figures/fig_framework.pdf figures/fig_flow_*.pdf figures/fig_model_*.pdf figures/fig_pipeline.pdf figures/fig_index_*.pdf figures/fig_network.pdf figures/fig_scene*.pdf; do
    [ -f "$pdf" ] || continue
    bn=$(basename "$pdf")
    # Use Python to check PDF page dimensions if possible
    dims=$($PYTHON -c "
try:
    from PyPDF2 import PdfReader
    r = PdfReader('$pdf')
    p = r.pages[0]
    w = float(p.mediabox.width) * 0.3528  # points to mm
    h = float(p.mediabox.height) * 0.3528
    ratio = h / w if w > 0 else 0
    print(f'{w:.0f}x{h:.0f}mm ratio={ratio:.2f}')
    if h > 250: print('TOO_TALL')
    if ratio > 1.8: print('TOO_NARROW')
except: pass
" 2>/dev/null)
    if echo "$dims" | grep -q 'TOO_TALL'; then
        echo "  ⚠ $bn 高度超过 250mm — 编译后可能占满整页，建议压缩"
        HUGE=$((HUGE+1))
    fi
    if echo "$dims" | grep -q 'TOO_NARROW'; then
        echo "  ⚠ $bn 宽高比过窄 — 用 width=0.6\\textwidth 而非 \\textwidth"
        HUGE=$((HUGE+1))
    fi
done
[ "$TINY" -eq 0 ] && echo "✅ All PDFs non-trivial" || { echo "❌ $TINY tiny/broken PDFs"; GATE_FAIL=$((GATE_FAIL+1)); }
[ "$HUGE" -eq 0 ] && echo "✅ All PDFs reasonable size" || echo "⚠ $HUGE oversized PDFs — adjust width in latex_includes.tex"

echo ""
[ "$GATE_FAIL" -eq 0 ] && echo "✅ ALL PASSED — figures ready for paper writing" || echo "❌ $GATE_FAIL FAILURES — fix and re-run"
```

**⛔ If GATE_FAIL > 0, fix every ❌ and re-run. Do NOT finish with any ❌.**

## Key Rules

- Data figures must be PDF. Do not use pgfplots to draw from CSV (path/column/encoding issues)
- DrawIO .drawio files export to PDF via `draw.io.exe --export --format pdf --crop`
- Primary output: `figures/` directory
- Temp files: `_tmp/`
- One script per figure, independently re-runnable
- Read data from JSON/CSV, do not hardcode values

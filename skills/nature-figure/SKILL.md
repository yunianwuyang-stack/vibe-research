---
name: nature-figure
description: "Generate publication-ready matplotlib figures matching Nature journal standards. Use when user says 'Nature figure', 'Nature style plot', or needs high-impact journal figures with Nature typography, color systems, and SVG/PDF export."
argument-hint: [figure-plan-or-data-path]
allowed-tools: Bash(*), Read, Write, Edit, Grep, Glob, Agent, mcp__codex__codex, mcp__codex__codex-reply
---

# Nature Figure: Publication-Quality Figures for Nature/High-Impact Journals

Generate Nature-style figures from: **$ARGUMENTS**

## Constants

- **FIG_DIR = `figures/`**
- **PRIMARY_FORMAT = `pdf`** (LaTeX embedding, vector)
- **DPI = 300**
- **CUSTOM_REQUIREMENTS** — User-specified requirements, highest priority.

## 用户数量硬下限（竞赛 / 论文高级选项）

开始前必须读取工作流注入的数量契约：

```bash
source .env_skill 2>/dev/null || true
echo "MIN_FIGURES=${MIN_FIGURES:-auto} MIN_TABLES=${MIN_TABLES:-auto}"
```

- 若 `MIN_FIGURES` 是大于 0 的整数，必须至少生成该数量的独立 Nature 数据图。
- 若 `MIN_TABLES` 是大于 0 的整数，必须至少生成该数量的独立数据表。PDF/LaTeX 输出使用
  `figures/TABLE_<id>.tex`，Word 输出使用 `figures/TABLE_<id>.md`；同一 `<id>` 的多格式副本只算
  1 个表格。
- `TABLE_<id>` 必须是稳定、唯一、具有语义的 ID（例如 `TABLE_ablation`），不得用复制同一张表、
  改扩展名或编号别名凑数。
- 图表计划少于硬下限时，先扩展计划再生成。结束前逐一检查所有 `TABLE_<id>` 文件；引擎会按唯一
  ID 生成 `QUANTITY_MANIFEST.json` 并执行 terminal gate，数量不足会使本步骤失败并进入恢复循环。

## 📊 Recipe Library Reference (for layout inspiration only — colors stay Nature)

If `PAPER_PLAN.md`'s FIGURE_MANIFEST contains recipe annotations like `fig_q1 // empirical#8`,
you **may** read the corresponding recipe's *layout / annotation style* as a starting point.
However, **colors, fonts, font sizes, line widths, and figure dimensions must strictly follow
Nature's `PALETTE_NATURE` and rcParams** defined below — do **not** copy recipe colors/styles.

```bash
# Read a recipe for layout reference (NOT for colors)
python3 _utils/get_recipe.py empirical 8 2>/dev/null \
  || cat skills/shared-scripts/figure_recipes_empirical.md
```

**Recipe libraries available** (browse for layout inspiration only):
- `basic` / `advanced` / `empirical` / `academic` — generally suitable for Nature-style charts
- `competition` — ⛔ avoid: contest-style charts (Pareto fronts, convergence curves) do not match Nature aesthetics

**Override checklist when using a recipe as starting point:**
- Replace all colors with `PALETTE_NATURE`
- Set `plt.rcParams` per Nature spec (font: Arial/Helvetica 7pt, line width 0.5pt, single-column 89mm)
- Strip recipe-specific decorations (no gradient fills unless single-column heatmap; no Rain Cloud violins)
- Remove `plt.title()` (Nature figures use external captions)

---

## ⛔⛔⛔ Figure Completeness (HIGHEST PRIORITY — prevents "broken / partial" figures)

Nature style is minimal, but **minimal ≠ broken**. Users reported figures that came out as **floating colored blocks with no axes, no ticks, no curves** (e.g. a lone green shaded area, or scattered rectangles). Every figure MUST stay fully readable. Hard rules:

1. **Y-axis MUST keep numeric ticks.** Never call `ax.set_yticks([])` on a data plot — an axis with no scale is unreadable. Sparse (3–5 ticks) is fine, empty is forbidden.
2. **Both `ax.set_xlabel(...)` and `ax.set_ylabel(...)` are mandatory**, with units (e.g. `Time (h)`, `RMSE`). No bare/unlabeled axes.
3. **If you hide x-ticks (`ax.set_xticks([])`), you MUST directly label the data** (`ax.bar_label`, `ax.text`, or `annotate`). Hiding ticks WITHOUT direct labels = broken figure.
4. **Every `fill_between` / confidence band MUST be drawn together with its main line** (`ax.plot(...)`). A standalone shaded area with no curve and no axis is meaningless — this is exactly the "green blob" users complained about.
5. **`ax.set_frame_on(False)` is allowed ONLY for heatmaps / image plates**, never for line / bar / scatter plots — those keep left + bottom spines.
6. **Multi-panel: every subplot must have its own visible axes + labels.** Never leave bare colored rectangles floating with no axis.

⛔ **竞赛 / 中文论文场景**：评委需要完整可读的图（坐标轴 + 刻度 + 单位 + 图例或直接标注齐全）。Nature 的"省略图例 / 隐藏刻度 / 直接标注"只在仍能保证可读时才用，**绝不能产出只剩色块的残图**。每画完一张图，肉眼自检：去掉 caption 后，单看这张图能不能读懂坐标含义？不能就是残图，必须补全。

## Mandatory rcParams (apply at top of EVERY script)

```python
import matplotlib.pyplot as plt

plt.rcParams['font.family'] = 'sans-serif'
plt.rcParams['font.sans-serif'] = ['Arial', 'DejaVu Sans', 'Liberation Sans']
plt.rcParams['svg.fonttype'] = 'none'          # editable text in SVG/PDF
plt.rcParams['font.size'] = 16                 # 24 for large bar panels
plt.rcParams['axes.spines.right'] = False
plt.rcParams['axes.spines.top'] = False
plt.rcParams['axes.linewidth'] = 2.5           # 3 for big bars, 2 for compact
plt.rcParams['legend.frameon'] = False
```

### Integration with plot_utils.py

Try `setup_style(palette='nature')` first. If unavailable, use inline rcParams above as fallback:

```python
import os, sys, shutil
os.makedirs('_utils', exist_ok=True)
for src in ['plot_utils.py']:
    for search in ['skills/shared-scripts', '../skills/shared-scripts']:
        p = os.path.join(search, src)
        if os.path.isfile(p):
            shutil.copy2(p, f'_utils/{src}')
            break
sys.path.insert(0, '.')
try:
    from _utils.plot_utils import setup_style, save_fig, PALETTE
    setup_style(palette='nature')
except (ImportError, TypeError):
    # Fallback: apply Nature rcParams directly
    plt.rcParams['font.family'] = 'sans-serif'
    plt.rcParams['font.sans-serif'] = ['Arial', 'DejaVu Sans', 'Liberation Sans']
    plt.rcParams['svg.fonttype'] = 'none'
    plt.rcParams['font.size'] = 16
    plt.rcParams['axes.spines.right'] = False
    plt.rcParams['axes.spines.top'] = False
    plt.rcParams['axes.linewidth'] = 2.5
    plt.rcParams['legend.frameon'] = False
```

## Nature Color Palette

```python
PALETTE_NATURE = {
    "blue_main":      "#0F4D92",   # deep blue — hero method
    "blue_secondary": "#3775BA",   # medium blue
    "green_1": "#DDF3DE",          # light positive
    "green_2": "#AADCA9",          # mid positive
    "green_3": "#8BCF8B",          # strong positive
    "red_1":   "#F6CFCB",          # light baseline
    "red_2":   "#E9A6A1",          # mid baseline
    "red_strong": "#B64342",       # strong baseline/negative
    "neutral_light": "#CFCECE",
    "neutral_mid":   "#767676",
    "neutral_dark":  "#4D4D4D",
    "neutral_black": "#272727",
    "gold":   "#FFD700",
    "teal":   "#42949E",
    "violet": "#9A4D8E",
}

# For unified-family figures (NMI-style dense pages)
PALETTE_NMI_PASTEL = {
    "baseline_dark": "#484878",
    "baseline_mid":  "#7884B4",
    "baseline_soft": "#B4C0E4",
    "ours_tiny":  "#E4E4F0",
    "ours_base":  "#E4CCD8",
    "ours_large": "#F0C0CC",
    "delta_up":   "#2E9E44",
    "delta_down": "#E53935",
}
```

Semantic rules:
- Blue = proposed/hero method
- Green = positive variants/improvements
- Red/pink = baselines/contrast
- Neutral grays = reference/background
- Use NMI pastel when comparing method families on dense pages

## Default Operating Stance

1. **Classify** the figure into one of 5 Nature page archetypes (see below)
2. **Hero panel** concept: one dominant panel + subordinate evidence panels
3. **Direct labels** over legends when categories are spatially fixed
4. **White background** for plots; black only for microscopy/imaging plates
5. **One restrained palette** per figure: neutral + signal + accent families
6. **Panel labels**: small bold lowercase (a, b, c) near top-left edge

## 5 Nature Page Archetypes

| Archetype | Layout | When to use |
|-----------|--------|-------------|
| Schematic-led composite | Wide story panel + smaller quant panels below | Method explanation + validation |
| Dark image plate | Black tiles with fluorescent channels | Microscopy, imaging, volume rendering |
| Clinical triptych | Top longitudinal, middle forest, bottom summary | Clinical/longitudinal studies |
| Dense categorical | Grid of equal panels, unified palette | Multi-metric comparisons |
| Asymmetric hero | One dominant panel spanning grid cells + small supports | Single key result + context |

## Layout Rules

- Hero panel gets visual hierarchy; support panels validate, not compete
- Panel labels: `ax.set_title('a', loc='left', pad=3, fontsize=14, fontweight='bold')`
- Tight gutters; increase spacing when dark/light modalities touch
- Prefer shared legend strip above a row over per-panel legends
- Dynamic y-axis: tighten to data range, never fixed 0–100 for narrow bands
- figsize guidance: journal-width composite (7.0–7.4, 5.5–7.8); bar panels (28–45, 6–12)

## Export Policy

**根据工作流模式选择输出格式（查看 CLAUDE.md 末尾的格式指令）：**

```python
import os
os.makedirs('./figures/', exist_ok=True)
fig.tight_layout(pad=0.5)

# 默认（LaTeX 模式）— 只输出 PDF（矢量、给 \includegraphics 用）
save_fig(fig, './figures/name.pdf')

# Word 模式（CLAUDE.md 含「⛔ 输出格式：仅 PNG」时）— 只输出 PNG（350 DPI）
# save_fig(fig, './figures/name.png')
```

- **LaTeX 模式：只输出 PDF**（不要同时存 PNG，避免冗余）
- **Word 模式：只输出 PNG**（DPI 350 防中文糊；不要存 PDF，Word 不能嵌 PDF）
- `save_fig()` 自动加 `bbox_inches='tight'` 并 `plt.close(fig)`，无需手写
- 检查 CLAUDE.md 末尾决定用哪种格式

## Workflow

### Step 1: Read data + classify figure type

Read PAPER_PLAN.md and data files. For each figure, classify into archetype and choose palette.

### Step 2: Read references + Generate scripts

**⛔ 必须在写任何绑图脚本之前，先读取以下参考文件：**

```bash
# 必读：配色方案和 helper 函数
cat _references/api.md

# 必读：根据图表类型选择对应教程
cat _references/tutorials.md

# 按需读取（多面板/复杂布局时）
cat _references/common-patterns.md

# 按需读取（需要了解 Nature 真实页面风格时）
cat _references/nature-2026-observations.md

# 按需读取（雷达图/3D/特殊图表时）
cat _references/chart-types.md
```

One script per figure. Each starts with Nature rcParams setup (`setup_style(palette='nature')` or inline rcParams). Follow the patterns from `_references/tutorials.md` as starting point.

### Step 3: Execute and validate

Run each script. Verify PDF output exists in `figures/`. Check:
- No `plt.title()` (captions in LaTeX only)
- Font ≥ 9pt final size
- Grayscale-distinguishable
- Panel labels present for multi-panel figures
- Colors from Nature palette, not matplotlib defaults
- ⛔ **Completeness (anti-broken图)**: y-axis has numeric ticks (NOT empty); both `set_xlabel` & `set_ylabel` present with units; if x-ticks are hidden then data is directly labeled; every `fill_between` has an accompanying `plot` line; `set_frame_on(False)` only on heatmaps; no subplot is a bare colored rectangle. **Open each PNG/PDF and confirm it is not just floating color blocks — if it is, fix and re-run before continuing.**

### Step 4: Generate latex_includes.tex

Include all figures with `[H]` float specifier and English captions.

### Step 5: ⛔ FIGURE_MANIFEST 对账（按规划数量逐张核对，必跑）

**PAPER_PLAN.md 里规划了几张数据图，本步骤就必须产出几张。** 防止 context 中途爆掉只画了 1-2 张就退出的死循环 bug。

```bash
echo "=== FIGURE_MANIFEST 对账 ==="
PLAN_FILE=""
for f in PAPER_PLAN.md PROBLEM_ANALYSIS.md TOPIC_PLAN.md; do
  [ -f "$f" ] && grep -q "<!-- BEGIN FIGURE_MANIFEST -->" "$f" && { PLAN_FILE="$f"; break; }
done
PASS=true
if [ -n "$PLAN_FILE" ]; then
    START=$(grep -n "<!-- BEGIN FIGURE_MANIFEST -->" "$PLAN_FILE" | head -1 | cut -d: -f1)
    END=$(grep -n "<!-- END FIGURE_MANIFEST -->" "$PLAN_FILE" | head -1 | cut -d: -f1)
    # ⛔ 只对账「数据图」章节: 按 manifest 的粗体章节标题归类(权威), 不靠文件名前缀。
    #    这样 fig_data_pipeline/fig_model_arch 这类「关键词在中间」的架构图不会被误纳入
    #    数据图对账(它们归 DrawIO 章节, 由 paper-figure-drawio 负责); TikZ 章节也跳过。
    EXPECTED=$(sed -n "${START},${END}p" "$PLAN_FILE" \
        | awk '
            /^[[:space:]]*\*\*/ {
                if ($0 ~ /数据图/ || tolower($0) ~ /matplotlib|gen_fig/) cap=1; else cap=0;
                next
            }
            cap && match($0, /^[[:space:]]*-[[:space:]]+fig_[a-zA-Z0-9_]+/) {
                s=substr($0, RSTART, RLENGTH); sub(/^[[:space:]]*-[[:space:]]*/, "", s); print s
            }')
    miss=0
    for name in $EXPECTED; do
        if ! ls figures/${name}.pdf figures/${name}.png 2>/dev/null | head -1 | grep -q .; then
            echo "❌ 缺失数据图: $name"
            miss=$((miss + 1))
        fi
    done
    if [ "$miss" -gt 0 ]; then
        echo "⛔ FIGURE_MANIFEST 对账失败: 缺 $miss 张数据图，必须全部画出来再结束本步骤"
        PASS=false
    else
        echo "✅ 数据图全部产出"
    fi
else
    echo "(规划文档无 FIGURE_MANIFEST, 跳过对账)"
fi
[ "$PASS" != true ] && echo "⛔ 验证未通过 — 必须补齐缺失图表后再结束"
```

## Key Rules

- ⛔ Never use `svg.fonttype = 'path'` — breaks text editability
- ⛔ No `plt.title()` — captions belong in LaTeX
- ⛔ No matplotlib default colors — always use Nature palette
- ⛔ No grid lines by default — sparse y-ticks guide the eye
- Active voice in axis labels; concise legend entries
- For ablation: single color with varying alpha (0.2–1.0)
- Error bars: `elinewidth=2, capthick=2, capsize=10`
- Heatmap text contrast: white on dark cells, black on light cells

## Related Files

| File | Open when |
|------|-----------|
| [references/api.md](references/api.md) | Palette constants, helper function signatures, validation rules |
| [references/design-theory.md](references/design-theory.md) | Typography, color theory, layout rationale |
| [references/chart-types.md](references/chart-types.md) | Radar, 3D sphere, fill_between, scatter patterns |
| [references/common-patterns.md](references/common-patterns.md) | Ultra-wide panels, legend-only axes, print-safe bars |
| [references/nature-2026-observations.md](references/nature-2026-observations.md) | Real Nature page archetypes from 2026 issues |
| [references/tutorials.md](references/tutorials.md) | End-to-end walkthroughs: bars, trends, heatmaps |
| `_utils/plot_utils.py` | Shared plotting infrastructure |

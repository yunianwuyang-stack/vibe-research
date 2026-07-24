---
name: paper-figure-html
description: "用 HTML+CSS 画流程图/技术路线图/系统架构图/流水线/框架矩阵图，再用 Electron printToPDF 转成矢量 PDF 供论文 \\includegraphics 引用。paper-figure-drawio 的 HTML 平替（默认）。当用户说\"画HTML图\"、\"技术路线图\"、\"流程图\"或需要论文非数据类示意图时使用。"
argument-hint: [figure-plan-or-data-path]
allowed-tools: Bash(*), Read, Write, Edit, Grep, Glob, Agent
---

# Paper Figure — HTML/CSS 矢量图（Sub-step）

用 HTML+CSS 生成论文非数据类示意图：**$ARGUMENTS**

这是从 paper-figure 拆出的**轻量子步骤**，是 `paper-figure-drawio` 的 **HTML 平替**（用户可二选一，HTML 为默认）。只处理架构/流程/路线类示意图，数据图（matplotlib/seaborn）已在前一步 paper-figure 生成。

**HTML 相对 DrawIO 的核心优势**：用 flex/grid 自动布局，不写绝对坐标 → 天然免疫节点重叠/坐标错位/连线穿越。因此本 skill **不需要** drawio 的坐标结构自检（drawio_check.py），改用 HTML/PDF 专属质检。

## ⚡ 快速模式检测（开头先跑）

```bash
FAST_MODE=0
grep -q 'VIBE_FAST_MODE=1' CLAUDE.md 2>/dev/null && FAST_MODE=1
echo "FAST_MODE=$FAST_MODE"
```

**若 `FAST_MODE=1`（速度优先）：** 仍按图表清单产出所有图（一张不漏、能出 PDF、过 html_pdf_check），但**跳过** vision 视觉自检的多轮修复循环——生成即用，仅当 html_pdf_check FAIL 或明显空图时才补。**若 `FAST_MODE=0`（默认）：** 视觉自检修复循环照常执行。

## Constants

- **FIG_DIR = `figures/`**
- **CUSTOM_REQUIREMENTS** — 用户自定义要求，最高优先级。

## ⛔ 工具路径解析（每次开头先跑，后续步骤都用这些变量）

本 skill 的模板、主题、渲染器和质检脚本均以明文随 skill 发布；运行器通过
`$CLAUDE_SKILL_DIR` 暴露其绝对目录。旧版工作区的 `_templates/` / `_utils/` 仍作为兼容
回退。渲染器会优先调用 Chromium/Chrome/Edge 生成静态 PNG/PDF；浏览器不可用时会用
Pillow/标准库生成带降级说明的非空静态产物与 `.capture.json`，绝不悄悄留下空图。

```bash
PYTHON=$(command -v python 2>/dev/null || command -v python3 2>/dev/null)
# ⛔ 这台机器必须用 python，不能用 python3（python3 触发 Microsoft Store 存根，exit 49）

# 模板目录：优先 _templates/，回退到 skill 源目录
TPL_DIR=""
for d in "$CLAUDE_SKILL_DIR/templates" _templates skills/paper-figure-html/templates _utils; do
  if [ -f "$d/tpl_roadmap.html" ]; then TPL_DIR="$d"; break; fi
done
echo "模板目录 TPL_DIR=$TPL_DIR"

# 出图工具（screenshot_capture.py，后端复制进 _utils/）
CAPTURE=""
for f in "$CLAUDE_SKILL_DIR/tools/render_html.py" _utils/screenshot_capture.py tools/screenshot_capture.py; do
  [ -f "$f" ] && { CAPTURE="$f"; break; }
done
echo "出图工具 CAPTURE=$CAPTURE"

# HTML/PDF 质检脚本（优先 _utils/，回退 _templates/、skill 源目录）
HTMLCHECK=""
for f in "$CLAUDE_SKILL_DIR/tools/html_pdf_check.py" _utils/html_pdf_check.py _templates/html_pdf_check.py skills/paper-figure-html/tools/html_pdf_check.py; do
  [ -f "$f" ] && { HTMLCHECK="$f"; break; }
done
echo "质检脚本 HTMLCHECK=$HTMLCHECK"

# 视觉自检脚本（复用 drawio_vision_check.py，与画图引擎无关；不存在则跳过视觉自检）
VISION=""
for f in _utils/drawio_vision_check.py tools/drawio_vision_check.py; do
  [ -f "$f" ] && { VISION="$f"; break; }
done
echo "视觉自检 VISION=${VISION:-（不可用，将跳过视觉自检）}"

# ===== TikZ 依赖（仅当规划有精密几何图才用；公式本身走 HTML+KaTeX，几何示意才靠 xelatex 编译 TikZ）=====
# 规则文档（物理尺寸/字号/scale 匹配规则）
TIKZ_RULES=""
for f in _utils/tikz_rules.md skills/shared-scripts/tikz_rules.md; do
  [ -f "$f" ] && { TIKZ_RULES="$f"; break; }
done
echo "TikZ 规则 TIKZ_RULES=${TIKZ_RULES:-（无，将用内置规则）}"

# tikz_check.sh 结构自检脚本
TIKZ_CHECK=""
for f in _utils/tikz_check.sh skills/shared-scripts/tikz_check.sh; do
  [ -f "$f" ] && { TIKZ_CHECK="$f"; break; }
done
echo "TikZ 自检 TIKZ_CHECK=${TIKZ_CHECK:-（不可用，将跳过结构自检）}"

# tikz_vision_check.py 视觉自检（与 drawio_vision_check 同源，接受 PNG）
TIKZ_VISION=""
for f in _utils/tikz_vision_check.py tools/tikz_vision_check.py; do
  [ -f "$f" ] && { TIKZ_VISION="$f"; break; }
done
echo "TikZ 视觉自检 TIKZ_VISION=${TIKZ_VISION:-（不可用，将跳过）}"

# xelatex（TikZ 编译器；不存在则本机无 TikZ 能力，跳过 TikZ 只出 HTML 图）
XELATEX=$(command -v xelatex 2>/dev/null)
echo "TikZ 编译器 XELATEX=${XELATEX:-（不可用，将跳过 TikZ 图）}"
```

## ⛔⛔⛔ Output Contract（最高优先级）

**必须产出至少 1 张 `figures/fig_*.pdf`，并更新 `figures/latex_includes.tex`**。产物契约与 paper-figure-drawio **完全一致**（后端按同一口径对账，两个 skill 可互换）：

- 图名前缀固定：`fig_arch`（架构）/ `fig_flow`（流程，如 `fig_flow_q1`）/ `fig_roadmap`（技术路线）/ `fig_pipeline`（流水线）/ `fig_framework`（框架）。
- 中间产物是 `figures/fig_*.html`，最终产物是同名 `figures/fig_*.pdf`。
- ⛔ **图内绝不放标题**：标题一律由 LaTeX `\caption{}` 管理（避免标题重复、字体不一致）。
- ✅ **流程/算法/架构图里的公式可直接写在 HTML 里**：节点文字内用 `\( ... \)`（行内）或 `\[ ... \]`（独立行）写 LaTeX，出图时命令带 `--render-math`（见 Step 3），截图管线会注入 KaTeX 把它们渲染成真公式（矢量、可放大不糊）。不再需要为了几个公式就整张图退回 TikZ。
- ⛔ **只有"精密几何示意图"才走 TikZ**：需要按真实坐标画点/线/角度/向量场的几何图（如绳系摆几何、光路、受力分解），HTML 的 flex 相对布局摆不准，才用 TikZ 编译（见 Step 5.5）。产物 `figures/tikz_*.pdf` + 同名 `.tex`，写进 `latex_includes.tex`。⛔ 仅当规划清单明确要求这类几何图时才生成，无则跳过。

⛔ **特殊豁免**：若 PAPER_PLAN.md 明确无架构图/流程图需求（纯文字论文/数据分析报告），允许跳过本 skill 的产物要求；但仍要保留已有 `figures/latex_includes.tex` 不破坏。

⛔ **结束前必须跑产物校验**：

```bash
PASS=true
mkdir -p figures
PDF_COUNT=$(ls figures/fig_*.pdf 2>/dev/null | wc -l)
PLAN_NEEDS_DIAGRAM=$(grep -iE 'html|架构图|流程图|技术路线|fig_arch|fig_flow|fig_roadmap|fig_pipeline|fig_framework' PAPER_PLAN.md PROBLEM_ANALYSIS.md 2>/dev/null | wc -l)

# ⛔ 优先按 FIGURE_MANIFEST 对账：规划的每张图必须产出
PLAN_FILE=""
for f in PROBLEM_ANALYSIS.md PAPER_PLAN.md MODELING_REPORT.md; do
  [ -f "$f" ] && grep -q '<!-- BEGIN FIGURE_MANIFEST -->' "$f" && { PLAN_FILE="$f"; break; }
done

if [ -n "$PLAN_FILE" ]; then
    START=$(grep -n '<!-- BEGIN FIGURE_MANIFEST -->' "$PLAN_FILE" | head -1 | cut -d: -f1)
    END=$(grep -n '<!-- END FIGURE_MANIFEST -->' "$PLAN_FILE" | head -1 | cut -d: -f1)
    MANI=$(sed -n "${START},${END}p" "$PLAN_FILE")
    # ⛔ 按 manifest「HTML/DrawIO 章节」标题抓该章节下的全部图名（权威），不靠文件名前缀白名单
    EXPECTED=$(printf '%s\n' "$MANI" | awk '
        /^[[:space:]]*\*\*/ { cap = (tolower($0) ~ /html|drawio|tikz/) ? 1 : 0; next }
        cap && match($0, /^[[:space:]]*-[[:space:]]+(fig_|tikz_)[a-zA-Z0-9_]+/) {
            s=substr($0, RSTART, RLENGTH); sub(/^[[:space:]]*-[[:space:]]*/, "", s); print s
        }')
    missing=0
    for name in $EXPECTED; do
        ls figures/${name}.pdf figures/${name}.html 2>/dev/null | head -1 | grep -q . || { echo "❌ MANIFEST: $name missing"; missing=$((missing+1)); }
    done
    if [ $missing -gt 0 ]; then
        echo "⛔ FIGURE_MANIFEST 对账失败（缺 $missing 张）"; PASS=false
    else
        echo "✅ FIGURE_MANIFEST 全部产出"
    fi
elif [ "$PDF_COUNT" -ge 1 ]; then
    echo "✅ figures/fig_*.pdf = $PDF_COUNT"
elif [ "$PLAN_NEEDS_DIAGRAM" -eq 0 ]; then
    echo "✓ 规划无架构图/流程图需求，跳过"
else
    echo "❌ 规划要求架构图/流程图但未生成"; PASS=false
fi
[ -f figures/latex_includes.tex ] || touch figures/latex_includes.tex
[ "$PASS" != true ] && echo "⛔ Output verification FAILED — must complete before ending"
```

## Workflow

### Step 0: 恢复检查（断线重跑必读）

⛔ 本步骤可能因断线/手动重跑被多次启动。每次启动前**必须**先扫描已有产物：

```bash
echo "=== 工作区扫描 ==="
HAS_HTML=$(ls figures/fig_*.html 2>/dev/null | wc -l)
HAS_PDF=$(ls figures/fig_*.pdf 2>/dev/null | wc -l)
HAS_TIKZ=$(ls figures/tikz_*.pdf 2>/dev/null | wc -l)
echo "  fig_*.html: $HAS_HTML, fig_*.pdf: $HAS_PDF, tikz_*.pdf: $HAS_TIKZ"
ls -la figures/fig_*.pdf figures/tikz_*.pdf 2>/dev/null | head -30
```

| 状态 | 行动 |
|---|---|
| 规划要求的图都已生成（含 .html + 对应 .pdf 且过 html_pdf_check；有公式图的 tikz_*.pdf 也在） | **跳到 Step 6（latex_includes 核对）**，验证通过即完成 |
| 部分已生成 | **只生成缺失的**（已有的不重画） |
| 啥都没有 | 从 Step 1 开始 |

⛔ **铁律**：已有的 `figures/fig_*.html` / `figures/fig_*.pdf` / `figures/tikz_*.pdf` 不要重写。

### Step 1: 读规划 + 确定要画哪些图 + 算风格种子

1. 选规划文档（按存在性优先级）并确定语言：

```bash
PLAN_DOC=""
for f in PROBLEM_ANALYSIS.md PROPOSAL.md PAPER_PLAN.md; do
    [ -f "$f" ] && { PLAN_DOC="$f"; break; }
done
echo "=== 使用规划文档: ${PLAN_DOC:-（无，将只画 1 张 fig_roadmap 兜底）} ==="

# 文献综述工作流不需要架构图，直接跳过
if [ -f LITERATURE_REVIEW.md ] && [ -z "$PLAN_DOC" ]; then
    echo "✅ 文献综述工作流不需要架构图，已跳过"; exit 0
fi

# 语言判定（comp_apmcm_zh 是中文赛项，先排除）
if grep -qi 'comp_apmcm_zh' "$PLAN_DOC" CLAUDE.md 2>/dev/null; then
    FIG_LANG="zh"
elif grep -qi 'MCM\|ICM\|APMCM\|comp_mcm\|comp_apmcm\|Language.*English\|语言.*English' "$PLAN_DOC" CLAUDE.md 2>/dev/null; then
    FIG_LANG="en"
else
    FIG_LANG="zh"
fi
echo "图内文字语言: $FIG_LANG"

echo "=== 规划中的架构/流程图清单 ==="
grep -A 60 -iE 'HTML|DrawIO|架构图|流程图|技术路线' "$PLAN_DOC" 2>/dev/null | grep -E '^\- \[ \]? *fig_(arch|flow|roadmap|pipeline|framework)' || echo "（未找到显式清单，按工作流类型决定）"

# ⛔ 判断规划里有没有「精密几何示意图」需求（只有它才走 TikZ）
# 注意：含公式的流程/算法/架构图不再走 TikZ —— 公式直接写进 HTML 节点，出图加
#       --render-math 由 KaTeX 渲染（见 Step 3、产物契约）。TikZ 只留给需要按真实
#       坐标画点/线/角度/向量的几何图（绳系摆、光路、受力分解等）。
NEED_TIKZ=0
if grep -qiE 'tikz|几何示意|几何图|受力分解|坐标.*示意|光路' "$PLAN_DOC" 2>/dev/null; then NEED_TIKZ=1; fi
# manifest 里出现 tikz_ 图名也算
grep -qE '^[[:space:]]*-[[:space:]]+tikz_' "$PLAN_DOC" 2>/dev/null && NEED_TIKZ=1
echo "需要 TikZ 几何图: $NEED_TIKZ（1=是，见 Step 5.5；0=否，跳过 TikZ）"
echo "（提示：含公式的流程/算法/架构图走 HTML+KaTeX，不计入 NEED_TIKZ）"
```

2. **⛔ 输出 HTML PLAN CHECKLIST（后续步骤对照用，规划清单就是合同）：**

工作流类型决定数量：
- **数模竞赛 / 科研流程**（有 PROBLEM_ANALYSIS.md）：按清单全部生成（roadmap + flow_q1/q2/pipeline 等），**至少 1 张 fig_roadmap 技术路线图**。
- **开题报告**（有 PROPOSAL.md）：**只生成 fig_roadmap**，不画 fig_flow_q1/q2。
- **课程/论文写作**（有 PAPER_PLAN.md）：按 PAPER_PLAN.md 列出的 fig_arch/fig_flow_*/fig_pipeline 生成。
- **精密几何图**（`NEED_TIKZ=1`）：另在 Step 5.5 生成 `tikz_*`（按坐标画点/线/角度/向量的几何示意，如绳系摆、光路、受力分解），HTML 图与 TikZ 图**互补不重复**——同一张图只归其中一种引擎。含公式的流程/架构图归 HTML（公式靠 KaTeX 渲染），不进 TikZ。

```
HTML PLAN CHECKLIST (from $PLAN_DOC):
[ ] 1. fig_roadmap   — 技术路线图 (tpl_roadmap, HTML)
[ ] 2. fig_flow_q1   — 问题一求解流程图 (tpl_flow, HTML；公式写 \(...\)，出图加 --render-math)
[ ] 3. fig_flow_q2   — 问题二求解流程图 (tpl_flow, HTML)
[ ] 4. fig_pipeline  — 数据处理流水线 (tpl_pipeline, HTML)
[ ] 5. tikz_geom     — 精密几何示意图 (TikZ, 仅 NEED_TIKZ=1 时)
Total: N 张（HTML M 张 + TikZ K 张）
```

3. **⛔ 计算「确定性风格种子」**（不再从 4 套预设里挑主题）。风格种子由**工作区目录名**（=工作流 ID）确定性哈希得来，保证：**同一篇论文所有图共用同一种子 → 视觉统一；不同论文/不同用户种子不同 → 风格各异；断线重跑种子不变 → 可复现**。

```bash
# 风格种子 = 工作流ID(工作区目录名)的确定性哈希
WFID=$(basename "$PWD")
if command -v cksum >/dev/null 2>&1; then
    SEED=$(printf '%s' "$WFID" | cksum | cut -d' ' -f1)
else
    # 降级：无 cksum 时用 python 算哈希（仍确定性）
    SEED=$("$PYTHON" -c "import sys,zlib;print(zlib.crc32(sys.argv[1].encode()))" "$WFID")
fi
H0=$(( SEED % 360 ))
# 回避刺眼黄绿[50,70) 与 高纯红[330,360)∪[0,10)
if { [ $H0 -ge 50 ] && [ $H0 -lt 70 ]; } || [ $H0 -ge 330 ] || [ $H0 -lt 10 ]; then H0=$(( (H0 + 40) % 360 )); fi
TONE=$(( SEED % 3 ))   # 造型基调: 0=极简线性  1=卡片描边  2=分区块面
echo "🎨 风格种子 SEED=$SEED  主色相 H0=$H0°  造型基调 TONE=$TONE（全篇共用这三个值）"
```

- **H0（主色相）** 是全篇配色的种子，Step 2 按《设计规范 B 节》从它 HSL 推导整套色板。
- **TONE（造型基调）** 决定全篇统一的造型档次（见《设计规范 D 节》）。
- **可选的学科微调**：若 `$PLAN_DOC` 明显是某学科（能源/经济/计算机…），允许把 H0 吸附到规范 B.1 列的友好色带；否则直接用种子值。**吸附也要全篇一致。**

⛔ 记下 `H0` / `TONE`，Step 2 每张图都按同一对值设计——**禁止逐图换色、禁止随机数/时间戳**。

### Step 2: 逐张自主设计并生成 HTML（读设计规范 → 按逻辑与种子设计 → 直接 Write）

⛔ **一次只画一张 → 转 PDF → 质检 → 过了再画下一张**（和 drawio 版"逐张画逐张检"一致，避免批量出错难定位）。

⛔ **不再"选模板填字"。** 每张图**由你按下方《AI 自主生成 HTML 流程图设计规范》从零设计** HTML/CSS：结构服从该图的真实逻辑，配色/造型由 Step 1 的 `H0`/`TONE` 推导。这样同篇视觉统一、异篇风格各异、同篇内每张图因逻辑不同而结构不同。

**产物文件名仍是固定契约**（后端对账依赖，名字不能改；只是内部结构你自由设计）：

| 图的用途 | 产物文件名 |
|---|---|
| 技术路线图（阶段推进/时间轴） | `fig_roadmap.html` |
| 求解流程图（每个子问题一张） | `fig_flow_q1.html` / `fig_flow_q2.html` … |
| 系统架构图（分层/模块） | `fig_arch.html` |
| 数据流水线（横向数据流） | `fig_pipeline.html` |
| 框架矩阵图（方法对比/多维） | `fig_framework.html` |

**对清单里每一张图，按顺序：**

1. **先读规范再动手**：通读本 SKILL 末尾《AI 自主生成 HTML 流程图设计规范》A–E 节。用一句话说清这张图的**逻辑流向**（如"q1 是线性四步预处理"、"q3 是带收敛判断的迭代循环"、"q5 是三模块并行汇合"），再按 A 节的「逻辑类型→布局范式」菜单选**最贴合**的范式——**不同子问题逻辑不同，就该长得不同**。⛔ 同时守 **A.1**：节点填这道题**特有的**方法/模型/判据实体（不写"数据预处理/建立模型"这类通用空词），并把方法**真实存在**的非平凡结构（校验回调/假设分支/收敛回环/多方法比选）挖出来画上——这是"有内核 vs 通用空壳"的分水岭。⛔ 复杂范式（分层架构/放射中心/贯穿侧栏/多分区）照 **A.2 骨架库**搭 flex/grid，别退化成一根线；出图前对照 **D.1 高级感五条**（字重层次/语义连线/副标题密度/唯一焦点/低饱和）逐条过。

2. **按种子推导配色/造型**：按 B 节从 `H0` 用 HSL 推导整套 `:root` CSS 变量；按 D 节 `TONE` 定造型档次。**全篇所有图共用同一 `H0`/`TONE`。**

3. **直接 Write 出 `figures/fig_xxx.html`**（自包含单文件），务必满足：
   - ⛔ **满足规范 0 节全部硬约束**（根容器+html+body 全 `width:fit-content`；flex/grid 自动布局禁 absolute；单文件禁外链；图内无标题；单页、宽高比 ≤8:1；公式用 `\(...\)`/`\[...\]` 写进节点、出图加 `--render-math` 渲染，只有精密几何图才走 TikZ）。
   - ⛔ **逻辑完美嵌入**：填规划文档里的**真实**方法名/步骤/模块/子问题，不留占位文字（"核心模型""方法A"要换成论文实际模型名、算法名）。
   - ⛔ **图内文字语言 = `$FIG_LANG`**（中文论文全中文，英文论文全英文）。

4. **模板仅作极端兜底参考**：`$TPL_DIR` 下 5 个 `.html` **不是必抄骨架**。仅当连续多轮自检失败、实在设计不出结构时，才 `cat "$TPL_DIR/tpl_flow.html"` 瞄一眼找灵感——正常流程**不读模板、不复制模板**。

5. **每张生成后立即验证文件存在**：
```bash
[ -f figures/fig_roadmap.html ] && echo "✅ fig_roadmap.html created" || echo "❌ MISSING"
```

### Step 3: 转 PDF（Electron printToPDF，矢量单页无白边）

对刚生成的 HTML 转 PDF：

```bash
# 无公式的图：
$PYTHON "$CAPTURE" --file figures/fig_roadmap.html --out figures/fig_roadmap.pdf --format pdf 2>&1 | tail -8
[ -f figures/fig_roadmap.pdf ] && echo "✅ fig_roadmap.pdf 已生成" || echo "❌ PDF 生成失败"

# 含公式的图（节点里写了 \(...\)/\[...\]）：必须加 --render-math，KaTeX 才会渲染公式
$PYTHON "$CAPTURE" --file figures/fig_flow_q1.html --out figures/fig_flow_q1.pdf --format pdf --render-math 2>&1 | tail -8
[ -f figures/fig_flow_q1.pdf ] && echo "✅ fig_flow_q1.pdf 已生成" || echo "❌ PDF 生成失败"
```

- `--format pdf`（或 out 以 .pdf 结尾）→ 量内容真实像素、页面设成刚好等于内容 → **单页、无白边、真矢量**（文字可选可搜、无限放大不糊），等效 drawio `--crop`。
- `--render-math` → 截图前注入 KaTeX 渲染 HTML 里的 `\(...\)`/`\[...\]`/`$$`。**图里有公式就必须加**；没公式不用加（无害但多一步）。素材缺失时自动降级（图仍出、公式不渲染），不阻断。
- `$CLAUDE_SKILL_DIR/tools/render_html.py` 会记录实际后端：`chromium` 表示浏览器静态捕获；
  `pillow-fallback` / `stdlib-fallback` 表示可靠降级。降级仍必须得到同名 PDF、PNG 和
  `.capture.json`，并在最终汇报中如实说明；不要把静态降级图冒充矢量浏览器输出。

### Step 4: html_pdf_check 质检（⛔ 每张必跑，FAIL 必修）

**每出一张 PDF 就跑一次**。4 项检查：①单页（最关键，多页=FAIL，LaTeX 只显示第一页会截断）②矢量（有字体对象，非整页位图）③裁切（页面尺寸异常）④宽高比（>8:1 给 WARN）。

```bash
$PYTHON "$HTMLCHECK" figures/fig_roadmap.pdf
# 退出码：0=通过(可能带WARN，不阻塞) 1=FAIL(必修) 2=无法检查(跳过)
```

**⛔ 若退出码 1（FAIL）**，按明细修复后**重新出 PDF 再检**，直到过：
- **多页** → 内容太多/太高：精简节点文字、减少条目、或调窄 `.fig` 的 width 让内容更紧凑；实在放不下就拆成两张图。改完回 Step 3 重出。
- **无字体/整页位图** → 检查 HTML 是否误用了 `<img>`/`canvas`/背景图代替文字，改回纯文本+CSS。
- **尺寸异常小/裁切** → 检查 `.fig` 是否 `display:inline-block` 且有内容、`body{margin:0}`。
- **宽高比过宽（WARN）** → 不阻塞，但建议：pipeline 让阶段换行、roadmap 改窄卡片。

退出码 2（如缺 PDF 解析条件）→ 跳过，不阻塞。

### Step 5: 视觉自检（vision LLM，复用 drawio_vision_check，⛔ 不阻塞）

html_pdf_check 只看 PDF 结构，看不出渲染后的视觉效果（文字挤、配色刺眼等）。这一步用 vision LLM 真正"看图"。**复用** `drawio_vision_check.py`（它接受 PDF/PNG，与画图引擎无关）。**FAST_MODE=1 时跳过本步。**

⛔ **执行原则**：vision 不可用（`$VISION` 为空 或退出码 2）就跳过，**绝不阻塞**；这是加分项不是硬门槛，3 轮仍未解决也继续。

```bash
if [ -z "$VISION" ] || [ "$FAST_MODE" = "1" ]; then
  echo "ℹ 跳过视觉自检（工具不可用或快速模式）"
else
  for pdf in figures/fig_*.pdf; do
    [ -f "$pdf" ] || continue
    bn=$(basename "$pdf" .pdf)
    for VROUND in 1 2 3; do
      echo "=== 视觉自检: $bn (round $VROUND) ==="
      VOUT=$($PYTHON "$VISION" "$pdf" 2>&1); VEXIT=$?
      echo "$VOUT"
      if [ "$VEXIT" -eq 0 ]; then echo "✅ $bn 视觉通过"; break
      elif [ "$VEXIT" -eq 2 ]; then echo "⚠ vision 不可用，跳过 $bn（不阻塞）"; break
      fi
      # VEXIT=1：有视觉问题
      if [ "$VROUND" -lt 3 ]; then echo "⛔ $bn 有视觉问题，读 HTML 修复后重出 PDF..."
      else echo "⚠ $bn 3 轮仍有问题，继续（不阻塞）"; fi
    done
  done
fi
```

**⛔ 当某张图返回 ISSUE（VEXIT=1）时，你必须逐步修复（不是只跑检测脚本）：**
1. 用 **Read** 读该图的 `figures/fig_xxx.html`。
2. 按 vision 反馈改（HTML 是相对布局，改法比 drawio 简单）：
   - "文字溢出/截断" → 加大对应节点 `min-width` 或缩短文字（CSS 已 wrap，一般是 width 太窄）。
   - "配色刺眼/杂乱" → 按《设计规范 B 节》从 `H0` 重新推导色板，饱和度 ≤55%、有意义色 ≤4，别自造高饱和色。
   - "布局松散/大片留白" → 内容居中的类已处理；检查是否漏填内容或容器过宽。
   - "出现 HTML 源码/黑背景" → 检查标签是否闭合、`body{margin:0}`。
3. **重新出 PDF**（Step 3 命令），再跑 html_pdf_check（Step 4），再回本步验证。
4. 重复直到通过或 3 轮用完（用完仍不过也继续，不阻塞）。

### Step 5.5: 生成 TikZ 几何示意图（⛔ 仅当 Step 1 判定 NEED_TIKZ=1；否则整步跳过）

⚠ **公式本身不用 TikZ**：流程/算法/架构图里的公式直接写进 HTML 节点，出图加 `--render-math` 由 KaTeX 渲染即可（见 Step 3）。本步只画 HTML 摆不准的**精密几何示意图**——需要按真实坐标画点/线/角度/向量场的图（绳系摆几何、光路、受力分解、坐标标注等），用 TikZ 编译成矢量 PDF。**无这类几何图需求（`NEED_TIKZ=0`）直接跳过本步。**

```bash
if [ "$NEED_TIKZ" != "1" ]; then
  echo "ℹ 规划无精密几何图需求，跳过 TikZ（Step 5.5）"
elif [ -z "$XELATEX" ]; then
  echo "⚠ 本机无 xelatex，无法编译 TikZ。公式图将缺失——如规划强依赖，请在环境装 TeX（xelatex）。"
else
  echo "=== 开始生成 TikZ 公式图 ==="
fi
```

**⛔ 若 `NEED_TIKZ=1` 且 `XELATEX` 可用，按下面做（否则跳过）：**

⛔⛔ **TikZ 物理尺寸 vs 字号匹配规则（避免"文字撞主图/标注互叠"）**：TikZ 默认 1 单位=1cm，`\small`≈0.35cm、`\footnotesize`≈0.30cm、`\tiny`≈0.20cm。

- ⛔ **铁律**：任何标注节点的可用空间 **≥ 字号 × 2**（留 50% 留白）。
- 📐 量出图的 width/height（cm）：若 `min(width,height) < 3cm` → **必须** `scale=2.0+`（建议 2.5/3）拉开物理距离（字号不变）。
- 标注层间距 < 0.5cm 会撞 → 拉大或减层。
- ❌ 别用 `\resizebox`/`\adjustbox{max width=...}` 去"放大小图"（会把字撑爆位置）；只有图本身 > textwidth 才用来缩小。

1. **读规则**（用变量，优雅降级）：
```bash
[ -n "$TIKZ_RULES" ] && cat "$TIKZ_RULES" || echo "（无 tikz_rules.md，按上面内置规则画）"
```

2. **写 TikZ 代码到 `figures/tikz_diagrams.tex`**（多张图用多个 `\begin{tikzpicture}`，每张前加 `\newpage` 便于后面拆页）。
   - ⛔ 中文用 xelatex + `\usepackage{ctex}`（或 `fontspec` 指定中文字体），否则中文丢失。
   - ⛔ **图内不写标题**（交给 LaTeX `\caption{}`）。
   - ⛔ 图内文字语言 = `$FIG_LANG`。

3. **编译 + 修复循环（最多 3 轮）**：
```bash
for TROUND in 1 2 3; do
  echo "=== TikZ 编译 round $TROUND ==="
  "$XELATEX" -interaction=nonstopmode -output-directory=figures figures/tikz_diagrams.tex 2>&1 | tail -12
  if [ ! -f figures/tikz_diagrams.pdf ]; then
    echo "⛔ 编译失败：检查数学模式配对/缺 \\usetikzlibrary/中文需 ctex。读 .tex 修复后进入下一轮"
    continue
  fi
  # 结构自检（有脚本才跑）
  if [ -n "$TIKZ_CHECK" ]; then
    bash "$TIKZ_CHECK" figures/tikz_diagrams.tex; TC=$?
    if [ "$TC" -gt 0 ]; then echo "⛔ tikz_check 有 $TC 个 CRITICAL，读 .tex 修复后重编"; continue; fi
  fi
  echo "✅ TikZ 编译通过 + 结构自检通过"; break
done
[ -f figures/tikz_diagrams.pdf ] || echo "⚠ 3 轮仍未出 TikZ PDF：尽量简化公式/减少标注层后再试；实在编不过就在该图位置留 LaTeX 注释说明缺图，不阻塞其余产物"
```

⛔ **失败兜底**：HTML 引擎**没有 drawio 可退**。若某公式图 3 轮编不出，**大幅精简**（去掉次要标注、拆成两张更简单的图、公式改行内文字描述）再试；仍不行则**保留其余已成功产物**，在 latex_includes.tex 该图位置写一行 `% TODO: tikz_xxx 编译失败，需人工补` 注释，**不阻塞整步结束**。

### Step 5.6: TikZ 视觉自检（vision LLM，⛔ 不阻塞；FAST_MODE=1 跳过）

结构自检看不出渲染后的视觉挤叠。这一步用 `tikz_vision_check.py`（接受 PNG）真正"看图"。**只检 TikZ 图**（同名 .tex 含 `\begin{tikzpicture}` 的 PDF），HTML 流程图前缀（`fig_arch/fig_flow_/fig_roadmap/fig_pipeline/fig_framework`）已在 Step 5 检过，这里排除。

```bash
if [ "$NEED_TIKZ" != "1" ] || [ -z "$TIKZ_VISION" ] || [ "$FAST_MODE" = "1" ]; then
  echo "ℹ 跳过 TikZ 视觉自检（无公式图/工具不可用/快速模式）"
else
  mkdir -p _tmp
  # 多页 tikz_diagrams.pdf 先拆单页便于逐张检
  command -v pdfseparate >/dev/null 2>&1 && [ -f figures/tikz_diagrams.pdf ] && \
    pdfseparate figures/tikz_diagrams.pdf figures/tikz_diagrams_%d.pdf 2>/dev/null
  # 收集所有 TikZ 图 PDF（tikz_ 前缀 或 同名 .tex 含 tikzpicture）；单次遍历 figures/*.pdf 防重复检
  for pdf in figures/*.pdf; do
    [ -f "$pdf" ] || continue
    bn=$(basename "$pdf" .pdf)
    case "$bn" in fig_arch*|fig_flow_*|fig_roadmap*|fig_pipeline*|fig_framework*) continue ;; esac
    tex="figures/${bn}.tex"; [ -f "$tex" ] || tex="figures/tikz_diagrams.tex"
    is_tikz=0
    [ "${bn#tikz_}" != "$bn" ] && is_tikz=1
    [ -f "$tex" ] && grep -q '\\begin{tikzpicture}' "$tex" 2>/dev/null && is_tikz=1
    [ "$is_tikz" = "1" ] || continue
    for VROUND in 1 2 3; do
      echo "=== TikZ 视觉自检: $bn (round $VROUND) ==="
      PNG_OK=0
      if command -v pdftoppm >/dev/null 2>&1; then
        pdftoppm -png -r 200 -singlefile "$pdf" "_tmp/${bn}_v" && PNG_OK=1
      fi
      [ "$PNG_OK" = "0" ] && { echo "⚠ 无 pdftoppm，无法转 PNG，跳过 $bn（不阻塞）"; break; }
      VOUT=$($PYTHON "$TIKZ_VISION" "_tmp/${bn}_v.png" 2>&1); VEXIT=$?
      echo "$VOUT"
      if [ "$VEXIT" -eq 0 ]; then echo "✅ $bn 视觉通过"; break
      elif [ "$VEXIT" -eq 2 ]; then echo "⚠ vision 不可用，跳过 $bn（不阻塞）"; break
      fi
      # VEXIT=1：读 $tex 按反馈改坐标/间距/scale/颜色 → 重编 xelatex → 再检
      if [ "$VROUND" -lt 3 ]; then
        echo "⛔ $bn 有视觉问题：读 $tex 修复（scale 不够加 scale=2.0；标注间距<0.5cm 拉到 0.8cm+；rotate=90 长文字留 y 跨度 1.5cm+）后重编"
        "$XELATEX" -interaction=nonstopmode -output-directory=figures "$tex" 2>&1 | tail -6
        command -v pdfseparate >/dev/null 2>&1 && [ -f figures/tikz_diagrams.pdf ] && \
          pdfseparate figures/tikz_diagrams.pdf figures/tikz_diagrams_%d.pdf 2>/dev/null
      else echo "⚠ $bn 3 轮仍有问题，继续（不阻塞）"; fi
    done
  done
fi
```

**⛔ 当某张返回 ISSUE（VEXIT=1）时，你必须逐步修复**：用 Read 读对应 `.tex`，按反馈调坐标/间距/节点宽度/scale/颜色，用 Edit 写回，重编 xelatex，再检——每轮"检→改→编→再检"，直到通过或 3 轮用完（不阻塞）。

### Step 6: 更新 latex_includes.tex（⛔ 每张都要有 include 块）

为每张 PDF **追加**（`>>`，不覆盖）一个 figure 块到 `figures/latex_includes.tex`。⛔ 前一步 paper-figure 已写入数据图的 include，本步只追加本 skill 的图，不破坏已有内容。

**尺寸规则**（width 决定实际大小，height 只是防溢出上限；`keepaspectratio` 下取更小约束，height 只会压小不会放大）：

| 图类型 | width | height（防溢出上限） |
|---|---|---|
| 技术路线图 | `\textwidth` | `0.85\textheight` |
| Pipeline | `\textwidth` | `0.6\textheight` |
| 架构图 | `0.9\textwidth` | `0.8\textheight` |
| 求解流程图 | `0.85\textwidth` | `0.85\textheight` |
| 框架矩阵 | `0.9\textwidth` | `0.6\textheight` |

⛔ 所有图必须有 `keepaspectratio`。⛔ caption 必须与论文语言一致，由你按图意写。

```latex
% === 技术路线图 ===
\begin{figure}[H]
\centering
\includegraphics[width=\textwidth,height=0.85\textheight,keepaspectratio]{figures/fig_roadmap.pdf}
\caption{整体技术路线图}\label{fig:roadmap}
\end{figure}
```

**⛔⛔ TikZ 公式图也必须写进 latex_includes.tex（最常被漏！）**：TikZ 编译出 `figures/tikz_diagrams.pdf`（多张图则是多页）。**每一页/每一张** TikZ 图都要有独立 `\includegraphics` 块，否则写作步骤读不到、论文缺图。

- 若 `tikz_diagrams.tex` 里有多个 `\begin{tikzpicture}` → 编出的 PDF 是多页 → 先 `pdfseparate figures/tikz_diagrams.pdf figures/tikz_diagrams_%d.pdf` 拆单页（Step 5.6 已拆），再为**每一页**各写一块，caption 与规划的 TikZ 条目一一对应。
- ⛔ caption 与论文语言一致。

```latex
% === TikZ 模型架构/几何/算法图 ===
\begin{figure}[H]
\centering
\includegraphics[width=0.85\textwidth,height=0.85\textheight,keepaspectratio]{figures/tikz_diagrams.pdf}
\caption{模型架构与变量关系示意}\label{fig:tikz_model}
\end{figure}
```

**追加后自检**：
```bash
echo "=== latex_includes.tex 追加验证 ==="
for pdf in figures/fig_*.pdf; do
    [ -f "$pdf" ] || continue
    bn=$(basename "$pdf")
    grep -q "$bn" figures/latex_includes.tex 2>/dev/null && echo "✅ $bn 有 include" || echo "❌ $bn MISSING — 需追加"
done
# ⛔ TikZ PDF（含多页拆分）也逐个核对 —— 最常被漏
for tpdf in figures/tikz_diagrams.pdf figures/tikz_diagrams_*.pdf figures/tikz_*.pdf; do
    [ -f "$tpdf" ] || continue
    tbn=$(basename "$tpdf")
    grep -q "$tbn" figures/latex_includes.tex 2>/dev/null && echo "✅ TikZ $tbn 有 include" || echo "❌ TikZ $tbn MISSING — 需追加"
done
DUPS=$(grep -oh '\\label{[^}]*}' figures/latex_includes.tex 2>/dev/null | sort | uniq -d)
[ -z "$DUPS" ] && echo "✅ 无重复 label" || echo "❌ 重复 label: $DUPS"
```
有 ❌ 立即修复（追加缺失 include / 改重复 label）。TikZ 的 ❌ 尤其不能放过。

### Step 7: 最终质量门（⛔ MUST PASS，不允许带 ❌ 结束）

```bash
echo "=========================================="
echo "  HTML FIGURE QUALITY GATE"
echo "=========================================="
GATE_FAIL=0
HTML_COUNT=$(ls figures/fig_*.html 2>/dev/null | wc -l)
PDF_OK=0
for hf in figures/fig_*.html; do
    [ -f "$hf" ] || continue
    bn=$(basename "$hf" .html)
    if [ -f "figures/${bn}.pdf" ]; then
        # 每张 PDF 过一遍 html_pdf_check（FAIL 计入门禁）
        $PYTHON "$HTMLCHECK" "figures/${bn}.pdf" >/tmp/_hc.txt 2>&1
        [ $? -eq 1 ] && { echo "❌ ${bn}.pdf html_pdf_check FAIL"; cat /tmp/_hc.txt | grep FAIL; GATE_FAIL=$((GATE_FAIL+1)); } || PDF_OK=$((PDF_OK+1))
    else
        echo "❌ ${bn}.html 无对应 PDF"; GATE_FAIL=$((GATE_FAIL+1))
    fi
done
rm -f /tmp/_hc.txt
[ "$HTML_COUNT" -gt 0 ] && echo "✅ HTML=$HTML_COUNT, PDF 过检=$PDF_OK" || echo "⚠ 无 HTML 图（若规划要求则为 FAIL）"

# TikZ 公式图（仅当规划要求；NEED_TIKZ=1）
if [ "${NEED_TIKZ:-0}" = "1" ]; then
    if [ -z "$XELATEX" ]; then
        echo "⚠ 规划需公式图但本机无 xelatex — 已在 latex_includes 留 TODO，不计 FAIL（环境限制）"
    elif ls figures/tikz_*.tex figures/tikz_diagrams.tex >/dev/null 2>&1; then
        TIKZ_PDF=$(ls figures/tikz_diagrams.pdf figures/tikz_*.pdf 2>/dev/null | head -1)
        if [ -n "$TIKZ_PDF" ]; then
            echo "✅ TikZ 源码 + 编译 PDF 存在"
            # 结构自检 CRITICAL 计入门禁
            if [ -n "$TIKZ_CHECK" ]; then
                for tf in figures/tikz_*.tex figures/tikz_diagrams.tex; do
                    [ -f "$tf" ] || continue
                    bash "$TIKZ_CHECK" "$tf" >/dev/null 2>&1
                    [ $? -gt 0 ] && { echo "❌ tikz_check CRITICAL in $(basename $tf)"; GATE_FAIL=$((GATE_FAIL+1)); }
                done
            fi
        else
            echo "❌ TikZ 源码存在但无编译 PDF"; GATE_FAIL=$((GATE_FAIL+1))
        fi
    else
        echo "❌ 规划需公式图但无 tikz_*.tex"; GATE_FAIL=$((GATE_FAIL+1))
    fi
fi

# latex_includes.tex 含本 skill 图的 include（HTML + TikZ）
if [ -s figures/latex_includes.tex ]; then
    N=$(grep -c 'fig_roadmap\|fig_flow\|fig_arch\|fig_pipeline\|fig_framework\|tikz_' figures/latex_includes.tex 2>/dev/null || echo 0)
    [ "$N" -gt 0 ] && echo "✅ latex_includes.tex 含 $N 条本 skill 图" || { echo "❌ latex_includes.tex 无本 skill 图 include"; GATE_FAIL=$((GATE_FAIL+1)); }
    # 有 TikZ PDF 时逐个核对 include（防漏）
    for tpdf in figures/tikz_diagrams.pdf figures/tikz_diagrams_*.pdf figures/tikz_*.pdf; do
        [ -f "$tpdf" ] || continue
        grep -q "$(basename $tpdf)" figures/latex_includes.tex 2>/dev/null || { echo "❌ TikZ $(basename $tpdf) 无 include"; GATE_FAIL=$((GATE_FAIL+1)); }
    done
else
    echo "❌ latex_includes.tex 缺失"; GATE_FAIL=$((GATE_FAIL+1))
fi

# 无损坏小 PDF（HTML + TikZ）
for pdf in figures/fig_*.pdf figures/tikz_*.pdf; do
    [ -f "$pdf" ] || continue
    sz=$(wc -c < "$pdf")
    [ "$sz" -lt 3000 ] && { echo "❌ $(basename $pdf) 仅 $sz 字节，疑损坏"; GATE_FAIL=$((GATE_FAIL+1)); }
done

echo ""
[ "$GATE_FAIL" -eq 0 ] && echo "✅ ALL PASSED" || echo "❌ $GATE_FAIL FAILURES — 逐个修复后重跑本门禁"
```

**⛔ 若 GATE_FAIL > 0**：逐个修复每个 ❌（重生成 HTML→重出 PDF→重检，或重编 TikZ，或追加 latex_includes），重跑门禁，直到 GATE_FAIL=0。若某张 HTML 图 html_pdf_check 反复多页，最后手段是拆图或大幅精简内容；若某张 TikZ 3 轮编不出，大幅精简后仍不行才留 TODO（环境限制不计 FAIL）。

**⛔ 全通过后输出最终 CHECKLIST 确认：**
```
HTML PLAN CHECKLIST (FINAL):
[✅] 1. fig_roadmap  — figures/fig_roadmap.pdf (XX KB) — html_pdf_check PASS
[✅] 2. fig_flow_q1  — figures/fig_flow_q1.pdf (XX KB) — html_pdf_check PASS
[✅] 3. tikz_model   — figures/tikz_diagrams.pdf (XX KB) — 编译+自检 PASS（仅 NEED_TIKZ=1）
[✅] latex_includes.tex — 含 N 条本 skill 图 include
ALL COMPLETE — paper-figure-html step finished successfully
```

## FIGURE_MANIFEST（后端按此对账图数量）

规划步骤（paper-plan 等）在规划文档里维护 `<!-- BEGIN FIGURE_MANIFEST -->` 区块，本 skill 据此对账。章节标题格式与 drawio 版保持一致，只把 "DrawIO" 字样改成 "HTML"。后端按**粗体章节标题里的关键词**归类（`html` 或 `drawio` 都归到本 skill/-drawio 这一类，两者互换），不看文件名前缀，所以 `fig_data_pipeline` 这类"关键词在中间"的名字也不会漏。

⛔ **几何图（TikZ）的 manifest 归属**：HTML 引擎下 TikZ 也由**本 skill** 产出，所以 TikZ 图名要放进**含 "HTML" 字样的章节**（或单独写一个标题里带 "HTML/TikZ" 的章节），这样后端才把它归到本 skill 的对账通道（后端第一优先匹配标题里的 `html`/`drawio` 关键词）。⛔ **不要**沿用 drawio 版把 TikZ 单列成 `**TikZ 图（paper-figure 产出）：**`——那个标题会被后端归到 `paper-figure`（数据图）通道，导致本 skill 产出的 tikz 图对不上账。

示例 manifest 区块（供规划步骤参考）：
```
<!-- BEGIN FIGURE_MANIFEST -->
**数据图（matplotlib gen_fig_*.py，paper-figure 产出 .png/.pdf）：**
- fig_data_dist
- fig_result_compare

**HTML 流程/架构图 + TikZ 公式图（paper-figure-html 产出 .html/.pdf + tikz_*.pdf）：**
- fig_roadmap
- fig_flow_q1
- fig_pipeline
- tikz_model
<!-- END FIGURE_MANIFEST -->
```

## Key Rules（速查）

- HTML 用 flex/grid 自动布局，**不写绝对坐标** → 免疫重叠/错位/连线穿越（相对 drawio 的核心优势）。
- 单文件自包含：CSS 变量内联在 `<style>`，**不引 CDN/网络资源**（离线环境），字体用系统栈 `"Microsoft YaHei","Noto Sans SC",sans-serif`。
- ⛔ 画布透明：`html`/`body`/`.fig` 背景一律 `transparent`，**整图不铺底色块**（融入论文页面），只有节点自身可浅填充。
- 出图：`$PYTHON "$CAPTURE" --file figures/fig_x.html --out figures/fig_x.pdf --format pdf` → 单页矢量无白边。
- ⛔ 用 `python` 不用 `python3`（本机 python3 触发 Store 存根，exit 49）。
- ⛔ **图内不写标题**，标题交给 LaTeX `\caption{}`。
- ⛔ 图内文字语言与论文一致。
- ⛔ 配色由 Step 1 风格种子 `H0` 按《设计规范 B 节》HSL 推导，全篇共用同一 `H0`/`TONE`；别自造高饱和色、别逐图换色、别用随机数。
- ⛔ 逐张画 → 转 PDF → html_pdf_check（FAIL 必修）→ vision 自检（不阻塞）→ 过了再画下一张。
- ⛔ 每张 PDF（含 TikZ）都要在 latex_includes.tex 有一个 `\includegraphics` 块。
- html_pdf_check 退出码：0=通过 / 1=FAIL 必修 / 2=无法检查跳过。多页 PDF 是最常见 FAIL（LaTeX 只显示第一页）。
- ✅ **公式直接写 HTML + `--render-math`**：流程/算法/架构图里的公式用 `\(...\)`/`\[...\]` 写进节点，出图命令加 `--render-math`（Step 3），KaTeX 渲染成矢量公式。**只有精密几何示意图**（按坐标画点线角度）才走 TikZ（Step 5.5，`NEED_TIKZ=1`，用 `xelatex` 编译，产物 `tikz_*.pdf`；编不出就精简重试，实在不行留 TODO 不阻塞其余产物）。
- ⛔ TikZ 图的 manifest 章节标题要带 "HTML" 字样（归本 skill 对账通道），别用 drawio 版的独立 "TikZ 图" 标题。
- ⛔ TikZ 视觉自检（Step 5.6）排除 HTML 流程图前缀（fig_arch/fig_flow_/fig_roadmap/fig_pipeline/fig_framework），只检同名 .tex 含 tikzpicture 的图。

---

## AI 自主生成 HTML 流程图设计规范

> Step 2 逐张设计时的唯一准绳。目标：**每张图的结构忠实于它自己的逻辑，配色/造型由风格种子确定性推导**，从而同篇统一、异篇各异、单张之间因逻辑不同而不雷同，同时始终高级、克制、符合科研/竞赛审美。

### 0 硬约束（⛔ 违反即出图失败，无例外）

1. **一路 `fit-content` 收缩到内容**：`html, body` 与最外层根容器都必须
   ```css
   html, body { margin:0; padding:0; width:fit-content; height:fit-content; background:transparent; }
   .fig { width:fit-content; height:fit-content; background:transparent; }
   ```
   根容器**不允许**出现固定像素宽（如 `width:640px`）或 `100%/100vw`——否则 Electron 会量到视口宽 1280px，PDF 右侧留大白边。留白靠内部 `padding`/`gap`，不靠外层撑宽。
2. **⛔ 整图不设背景色块**：`html`/`body`/`.fig` 背景一律 `transparent`，**不给整张画布铺任何底色**（哪怕近白 `#fff`/`#fafafa` 也不行）。图要能无缝融入论文页面，插进白底/浅灰底文档都不露出"这是一块带底色的图"的边界。只有**节点自身**可有浅填充（见 D 节 `--node-bg`），画布本身透明。
3. **flex/grid 自动布局，禁 `position:absolute` 定坐标**：节点、连线、分区一律用 flex/grid 排布。自动布局是"永不重叠/错位/连线穿越"的根本。
4. **单文件自包含，禁外链**：CSS 内联在 `<style>`；不引 CDN、不引网络字体、不引外部图片；字体用系统安全栈 `"Microsoft YaHei","Noto Sans SC","Segoe UI",sans-serif`。
5. **图内不写标题**：标题交给 LaTeX `\caption{}`，图里只有流程/结构本身。
6. **单页 + 宽高比 ≤ 8:1**：内容多时优先增高不增宽（或分区换行），别撑成超宽单行。
7. **公式写 `\(...\)`/`\[...\]`**：节点里的数学公式用 KaTeX 定界符包裹，出图加 `--render-math` 渲染；只有精密几何示意图（按坐标画点线角度）才走 TikZ（Step 5.5）。
8. **禁 emoji、禁装饰性图标字体**。

### A 结构忠实于逻辑（⛔ 废除"强制三件套"）

**旧规则已作废**：不再要求每张流程图都塞"判断分支+循环/分叉+双行节点"。**结构服务逻辑，不为花样而花样。** 线性的问题就画线性，迭代的问题才画循环，并行的问题才画分叉。

**设计前先用一句话说清这张图的逻辑流向**，再从下表按最贴合的范式选布局（可组合，但只选逻辑需要的）：

| 逻辑类型 | 适配布局范式 |
|---|---|
| 线性顺序（A→B→C→D） | 纵向主干 / 横向流水线 |
| 阶段推进 / 时间演进 | 时间轴 / 分层堆叠（自上而下阶段） |
| 有条件分支 | 分叉树（菱形判断→是/否两路） |
| 迭代 / 收敛 | 循环回流（带回边箭头 + 收敛判断出口） |
| 多任务并行后汇总 | 并行分叉→汇合 |
| 输入/处理/输出三段 | 横向泳道 / 左右对照 |
| 模块化系统 | 分层堆叠 / 矩阵网格 |
| 以核心方法为中心辐射 | 放射中心（中心节点四周挂子模块） |
| 方法/维度对比 | 矩阵网格 / 左右对照 |

**自检问题**：如果把某个判断/循环去掉后，这张图描述的逻辑依然成立——那这个判断/循环就是硬凑的，删掉。宁可结构简单而**准确**，不要为了"看起来复杂"而失真。

**不同子问题必须看得出差异**：q1/q2/q3 若算法逻辑不同（如线性预处理 vs 二分搜索 vs 迭代优化），它们的布局范式就应当不同——这正是本次改造的核心诉求。

**⛔ A.1 反"通用空壳"——图必须有这篇论文特有的内核（违反即返工）**

"结构服从逻辑"不是"允许偷懒画泛泛流程"。⛔ **严禁**画出换任何论文都成立的通用空壳，典型反例：

- 节点全是万能词：`数据采集 → 数据预处理 → 建立模型 → 模型求解 → 结果分析 → 结论建议`。这种图信息量≈0，谁都能套，**一律返工**。

**每张图必须做到两点：**

1. **节点承载实体，不写空词**：节点里填**这个子问题特有的**方法名/模型名/算法/判据/关键变量/关键约束，让内行一眼认出"这是在解这道题、用的是这个方法"。
   - ❌ `建立模型` → ✅ `多目标遗传算法 NSGA-II`、`时变需求下的库存 (s,S) 策略`、`基于 LCA 的碳足迹核算模型`
   - ❌ `数据预处理` → ✅ `3σ 剔除异常 + 样条插补缺失`、`滑动窗口去趋势`
   - ❌ `模型求解` → ✅ `Gurobi 求解 MILP（分支定界）`、`四阶 Runge-Kutta 数值积分`

2. **挖出方法真实的非平凡结构**：很多流程"看起来线性"，是因为没往深挖。建模过程通常**真实存在**结构特征——参数标定回调、假设检验分支、收敛判断回环、多方法并行对比后择优、灵敏度/稳健性反馈。**把真实存在的结构挖出来画上**（这不是硬凑，是忠实），图立刻有内核。
   - ⛔ 但仍守 A 节铁律：只画**真实存在**的结构，不为了"显得深"而编造一个原逻辑里没有的分支/循环。
   - 判据：问自己"这道题的方法，除了顺序执行，还有没有回头校验、条件切换、并行比选？"——有就画出来，别把它拉直成一根线。

**⛔ 内核自检（每张图出图前必过）**：把所有节点文字抄下来，遮住题目，问"光看这些节点，能认出这是哪类课题、哪个方法吗？"——认不出 = 太泛，回去填实体、挖结构，重画。

### A.2 复杂范式 CSS 骨架库（⛔ 复杂结构照此搭，别退化成一根线）

菜单里"分层架构""放射中心""贯穿侧栏"这类**高级范式**光有名字画不出档次。下面给**可直接照抄的 flex/grid 骨架**（配色变量按 B 节从 `H0` 推导，别照抄这里的示例数值）。用哪种取决于 A 节的逻辑，不是每张都套。

**骨架 1 · 分层系统架构 + 贯穿侧栏**（多层堆叠，每层多模块，右侧横切关注点贯穿全层）——适合系统/平台/数字孪生类：

```css
.fig{display:flex;flex-direction:row;align-items:stretch;gap:14px}  /* 主栈 + 侧栏并排 */
.stack{display:flex;flex-direction:column;gap:0}                     /* 各层竖向堆叠 */
.layer{background:var(--node-bg-2);border:1.1px solid var(--line);border-radius:8px;
  padding:11px 14px;display:flex;align-items:center;gap:14px}        /* 一层=分区块面 */
.layer .lname{writing-mode:vertical-rl;font-size:11px;font-weight:700;
  color:var(--primary-dark);letter-spacing:2px;white-space:nowrap}   /* 竖排层名 */
.mods{display:flex;gap:11px}                                         /* 层内模块横排 */
.flow{text-align:center;color:var(--line);font-size:15px;margin:3px 0}/* 层间数据流箭头 */
.side{background:var(--node-bg-3,var(--node-bg-2));border:1.1px solid var(--accent);
  border-radius:8px;padding:12px;display:flex;flex-direction:column;
  align-items:center;justify-content:center;gap:11px;align-self:stretch}/* 右侧贯穿栏 */
```
- 层间流写"↑ 决策下发　状态上报 ↓"这类**双向语义**，别只画单箭头。
- 侧栏放"横切关注点"（安全/监控/反馈闭环），用 `--accent` 虚线框区别于主栈——这是流程图做不到的架构感。

**骨架 2 · 放射中心（3×3 网格，核心引擎四周辐射）**——适合以某方法/引擎为中心统领子模块：

```css
.grid{display:grid;grid-template-columns:repeat(3,150px);grid-template-rows:repeat(3,auto);
  gap:20px 26px;align-items:center;justify-items:center}
.core{grid-column:2;grid-row:2;background:var(--primary);color:#fff;border-radius:12px;
  padding:16px 14px;font-weight:700;box-shadow:0 2px 6px rgba(0,0,0,0.08)}/* 正中核心 */
.node.in{border-color:var(--secondary)}   /* 上排=输入，按角色分色 */
.node.out{border-color:var(--accent)}     /* 下排=输出 */
```
- 中心 `core` 放主引擎，八格按"输入类/支撑类/输出类"分色，一眼看出数据从四周汇向中心再产出。

**骨架 3 · 多分区块面（泳道/阶段分区，区内放节点）**——适合分阶段、分主体的对照/推进：

```css
.zone{background:var(--node-bg-2);border:1.1px solid var(--line);border-radius:8px;
  padding:13px 16px;display:flex;flex-direction:column;align-items:center;gap:9px}
.zone .zt{font-size:11px;font-weight:700;color:var(--primary-dark);letter-spacing:1px}/* 区标题 */
.row{display:flex;gap:14px}                          /* 区内节点横排 */
.branch{display:flex;gap:52px;align-items:flex-start} /* 条件分支：多路并列 */
```
- 分支范式：判断菱形下接 `.branch`，每路一个 `.path`（含 `.lbl` 标"成立/违背"），再 `.merge` 汇合——用于假设检验、策略切换这类**真实条件分叉**。

**⛔ 骨架只是脚手架**：结构照搭，**节点文字必须换成本题真实实体**（守 A.1）；配色变量必须按 B 节从 `H0` 推导。骨架帮你达到复杂度下限，内核靠你填。

### B 配色配方（⛔ 从种子 H0 用 HSL 推导，示例数值不得照抄）

Step 1 已算出主色相 `H0`（0–359 的整数）。**按下表用 HSL 推导整套色板**，每张图开头写成 `:root` CSS 变量。同一篇论文所有图共用同一 `H0`，所以色板自动统一。

| 角色 | 变量 | 推导规则（H=色相 S=饱和 L=亮度） | 用途 |
|---|---|---|---|
| 主色 | `--primary` | `hsl(H0, 42%, 46%)` | 主节点边框/强调 |
| 主色深 | `--primary-dark` | `hsl(H0, 46%, 34%)` | 标题文字/主箭头 |
| 辅助色 | `--secondary` | `hsl((H0+30)%360, 30%, 52%)` | 次级节点 |
| 点缀色 | `--accent` | `hsl((H0+180)%360, 40%, 50%)` | 仅关键判断/结果，用量 ≤ 全图 10% |
| 画布底 | —（无变量） | `transparent` | ⛔ 整图不铺底色，画布透明（见 0 节第 2 条） |
| 节点底 | `--node-bg` | `hsl(H0, 22%, 96%)` | 普通节点填充（节点自身可有浅色，画布不行） |
| 节点底深 | `--node-bg-2` | `hsl(H0, 26%, 92%)` | 分区/表头填充 |
| 正文字 | `--text` | `hsl(H0, 15%, 20%)` | 节点内文字（非纯黑） |
| 弱文字 | `--muted` | `hsl(H0, 10%, 45%)` | 注释/次要说明 |
| 连线 | `--line` | `hsl(H0, 20%, 60%)` | 箭头/连线/边框 |

**⛔ 配色约束（违反即返工）：**
- 饱和度整体 **≤ 55%**（低饱和才高级；主色 42% 左右，辅助更低）。
- **画布背景必须 `transparent`**，不给整图铺任何底色（融入论文页面）；只有节点自身可用 `--node-bg` 浅填充。
- 文字**不用纯黑 `#000`**，用 `--text`（深但带色相）。
- 主文字与其背景**对比度 ≥ 7:1**（WCAG AAA；深字浅底自然达标，务必核对）。
- **有意义的颜色 ≤ 4 种**（主/辅/点缀/中性）；点缀色克制，只标"最该注意的一处"。
- **B.1 可选学科吸附**：若明确学科，可把 `H0` 吸附到友好色带再推导——能源/环境≈160–190（青绿）、经济/管理≈25–45（暖棕橙）、计算机/信息≈215–245（靛蓝）、通用工科≈205–225（灰蓝）。吸附后**全篇用吸附值**，不再逐图变。

### C 同篇统一 + 异篇不同（确定性，非随机）

- **种子 = 工作流 ID（工作区目录名）的哈希**（Step 1 已算）。同一篇论文所有图读到同一 `SEED`，因此配色/造型/布局倾向全篇一致。
- **不同论文/不同用户目录名不同 → SEED 不同 → H0/TONE 不同 → 整体风格明显不同。**
- **断线重跑同目录 → SEED 不变 → 风格可复现。**
- **单张图之间的差异只允许来自"逻辑不同"**（A 节的范式选择），不允许来自配色/造型漂移。
- ⛔ **绝对禁止**用随机数、时间戳、`$RANDOM`、当前时间等非确定性来源决定任何视觉参数。

### D 造型档次（由 TONE 选一种，全篇统一）

Step 1 的 `TONE`（0/1/2）决定全篇统一的造型基调：

| TONE | 基调 | 特征 |
|---|---|---|
| 0 | 极简线性 | 节点无填充或极浅填充，靠细边框+留白区分；连线为主角；最克制 |
| 1 | 卡片描边 | 节点是圆角卡片，`--node-bg` 浅填充 + `--line` 细描边 + 极淡阴影 |
| 2 | 分区块面 | 用 `--node-bg-2` 色块划分逻辑分区（泳道/分层），区内放节点 |

**通用造型规则（三种基调都遵守）：**
- **圆角统一**：全图同一圆角值（如 6px 或 8px），别混用。
- **边框 0.75–1.5px**，颜色用 `--line`；⛔ 禁粗黑边（`2px solid #000` 之类）。
- **阴影克制**：最多 `0 1px 3px rgba(0,0,0,0.06)`，透明度 ≤ 0.08；极简基调可完全不用阴影。
- **留白呼吸**：节点内 `padding` ≥ 10–16px，节点间 `gap` ≥ 14–20px。
- **字号层级**：主节点 14–16px、说明文字 12–13px、注释 11px；同层级字号一致。
- **箭头造型**：细箭头（用 CSS 三角或 `border` 画），颜色 `--line`；线宽与节点边框协调。
- **反面清单（出现即返工）**：高饱和原色（纯红/纯绿/纯蓝）、粗黑边、大面积渐变、多种圆角混用、彩虹配色、emoji、装饰性图标。

### D.1 高级科研审美细节（⛔ 这些细节决定"看起来高级"还是"像 PPT 草稿"）

造型基调对了只是及格，真正拉开档次的是下面这些**克制而精确**的细节。顶刊/顶会配图的共性是"信息密度高、视觉噪声低"：

**① 层次靠"轻重"而非"多色"**：同一张图里区分主次，优先用**字重 + 留白 + 深浅**，不是加新颜色。
- 主节点 `font-weight:700` + `--node-bg` 浅填充；次节点 `font-weight:400` + 无填充；标题级文字用 `--primary-dark`。
- ⛔ 别靠"每类一个颜色"区分——有意义色 ≤4 是硬线（B 节），层次用明度/字重拉开。

**② 连线是"信息"不是"装饰"**：
- 箭头细、短、语义化。多源汇入用倾斜箭头 `↘ ↓ ↙` 收拢到一点；回流/反馈用**虚线 + `--accent`** 与主流区分；双向流写清"上行/下行"语义。
- ⛔ 禁纯直角折线堆叠、禁多条线交叉穿越（flex/grid 天然避免，别手动 absolute 破坏它）。

**③ 副标题制造信息密度**：每个节点主标题下加一行 `.sub`（`font-size:10-11px；color:--muted`）写方法细节/参数/数据源（如 `RNA-seq`、`Gurobi 分支定界`、`SCADA 秒级`）。这一行是"内行感"的来源，也直接支撑 A.1 内核。

**④ 对齐与节奏**：
- 同层级节点**等宽等高**（`min-width` 统一），gap 统一；grid/flex 自动对齐，别留参差边缘。
- 分区块面用**同一 `border-radius`、同一 padding 节奏**；区与区间距 > 区内节点间距（制造分组感）。

**⑤ 强调唯一焦点**：全图**只留一个**最强视觉锚点（通常是核心引擎/最终结论），用实心 `--primary` 填充 + 白字；其余一律浅色描边。多个焦点 = 没有焦点。

**⑥ 单位与符号规范**：数学符号用真 Unicode（`≤ ≥ σ ε ×` 而非 `<= >= sigma`），下标用 `f₁ f₂`；术语中英一致（首次出全称+缩写，如 `双重差分 DID`）。

**⑦ 密度平衡**：节点文字控制在 4–10 字 + 一行副标题；超长拆两行或移到 `.sub`。宁可多一个节点，不要一个节点塞两行长句。

> 一句话：**低饱和配色 + 字重层次 + 语义化连线 + 副标题密度 + 唯一焦点**——这五条齐了，图就有科研高级感。

### E 自检清单（设计前 + 出图后各过一遍）

**设计前自问：**
1. 这张图的逻辑流向能用一句话说清吗？
2. 按 A 节，我选的布局范式贴合这个逻辑吗？有没有硬凑判断/循环？
3. 它和本篇其它图的逻辑不同吗？（不同就该长得不同）
4. （A.1）节点里填的是这道题**特有的**方法/模型/判据，还是"数据预处理/建立模型"这种谁都能套的空词？后者立即改。
5. （A.1）这个方法**真实存在**的非平凡结构（校验回调/假设检验分支/收敛回环/多方法比选）挖出来了吗？还是被我拉直成一根线了？

**出图后自检：**
1. 结构是否真实反映论文逻辑（方法名/步骤都是真的，无占位文字）？
2. 配色是否全部由 `H0` 按 B 节推导、协调低饱和、有意义色 ≤ 4？造型是否符合 `TONE`？
3. 是否满足 0 节**全部**硬约束（`fit-content` 收缩、**画布 `transparent` 无底色块**、无 absolute、无外链、无标题、单页、宽高比 ≤8:1）？
4. **（A.1 内核自检）遮住题目只看节点文字，能认出这是哪类课题、哪个方法吗？** 认不出 = 通用空壳，回去填实体、挖真实结构，重画。
5. `html`/`body`/`.fig` 有没有残留 `background:#fff`/`#fafafa`/带色底？有就改 `transparent`（融入论文页面）。
6. **（D.1 高级感）**字重层次拉开了吗？连线语义化了吗？每个节点有副标题吗？全图有且只有一个焦点吗？——五条齐了才算高级。
7. 与本篇已生成的图相比：配色/造型统一，但结构因逻辑而不同？

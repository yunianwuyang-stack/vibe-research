#!/usr/bin/env bash
# count_subproblems.sh —— 统一的"子问题数量"计数器（单一权威口径）
#
# 背景：赛题有几个子问题(Q1/Q2/...)是贯穿 建模→编程→论文 全链的核心契约。
# 历史 bug：comp-modeling / comp-code / comp-paper-zh 各自用不同正则数，口径漂移：
#   - 有的按"标题行"数(准)、有的按"全文出现次数"数(虚高) → 两个口径比大小恒误报
#   - 有的正则漏了阿拉伯数字("问题1"数不出来) → 漏问不告警
# 统一口径：只数"顶层标题行"里的子问题声明，同时支持 中文数字 / 阿拉伯数字 / Problem N。
#
# 用法：
#   bash _utils/count_subproblems.sh <file.md>
# 输出：一个整数（该文件里声明的子问题数，去重后）。文件不存在则输出 0。
#
# 判定规则（一行命中一个子问题，按编号去重）：
#   ^## 问题一 / ^### 问题二 / ^## 问题1 / ^## Problem 1 / ^## Question 3 等
#   —— 必须是 Markdown 标题行(以 # 开头)，避免正文里"针对问题一……"被误计。

f="$1"
if [ -z "$f" ] || [ ! -f "$f" ]; then
    echo 0
    exit 0
fi

# ⛔ 强制 UTF-8 locale：很多运行环境 LANG 为空，grep/sed 会按单字节处理 UTF-8 中文，
# 导致"问题一/问题二/问题三"的中文数字被截成相同字节前缀而误判去重。设 UTF-8 后按字符处理。
export LC_ALL=C.UTF-8 2>/dev/null || true
export LANG=C.UTF-8 2>/dev/null || true

# 判定规则：只看 Markdown 标题行(以 # 开头)里声明的子问题，避免正文"针对问题一…"被误计。
# 不用"中文数字字符类"(按字节易错)，改为匹配「标题行中出现 问题/Problem/Question + 紧跟的编号」，
# 用「整个标题行去重」来数唯一子问题数——同一子问题即使拆成多个小节标题也只算一次。
#
# 具体：抓取形如  ^##[#] ... 问题<编号>  的标题行，提取到"问题X"这个 token 后去重计数。
# - 中文："问题" 后跟任意一个中文数字或阿拉伯数字
# - 英文：Problem / Question 后跟数字
# 优先级 0：comp-prob-analysis 要求在报告开头写 "本赛题共 X 个子问题"，有则以声明为准
declared=$(grep -oE '本赛题共[[:space:]]*[0-9]+[[:space:]]*个子问题' "$f" 2>/dev/null | head -1 | grep -oE '[0-9]+' | head -1)
if [ -n "$declared" ] && [ "$declared" -gt 0 ] 2>/dev/null; then
    echo "$declared"
    exit 0
fi

# 中文数字 → 阿拉伯数字归一化，使 "问题一" 与 "问题1" 视为同一子问题（旧版会重复计数）
count=$(awk '
    BEGIN {
        cn["一"]=1; cn["二"]=2; cn["三"]=3; cn["四"]=4; cn["五"]=5;
        cn["六"]=6; cn["七"]=7; cn["八"]=8; cn["九"]=9; cn["十"]=10;
    }
    function norm(tok,   n, m) {
        if (match(tok, /[0-9]+/)) return "q" (substr(tok, RSTART, RLENGTH) + 0)
        n = 0
        if (match(tok, /十/)) {
            # 十 / 二十 / 十三 / 二十三
            split(tok, parts, "十")
            n = (parts[1] == "" ? 1 : cn[parts[1]]) * 10 + (parts[2] == "" ? 0 : cn[parts[2]])
        } else {
            n = cn[tok]
        }
        return "q" n
    }
    # 只处理标题行(以一个或多个 # 开头)
    /^##?#?#?[[:space:]]/ {  # 不用 {1,4} 区间：mawk/busybox awk 不支持，整条规则会静默失效
        line=$0
        # 匹配中文"问题X"（同一标题可能提到多个子问题，逐个抓）
        # 注意：norm() 内部也会调用 match()，会覆盖全局 RSTART/RLENGTH，
        # 必须先把偏移存到局部变量再调用，否则 substr 用错偏移 → 死循环
        while (match(line, /问题[[:space:]]*(一|二|三|四|五|六|七|八|九|十|[0-9])+/)) {
            rs=RSTART; rl=RLENGTH
            tok=substr(line, rs, rl)
            sub(/^问题[[:space:]]*/, "", tok)
            seen[norm(tok)]=1
            line=substr(line, rs+rl)
        }
        low=tolower($0)
        while (match(low, /(problem|question)[ ]*[0-9]+/)) {
            rs=RSTART; rl=RLENGTH
            tok=substr(low, rs, rl)
            seen[norm(tok)]=1
            low=substr(low, rs+rl)
        }
    }
    END { print length(seen) }
' "$f" 2>/dev/null)

echo "${count:-0}"

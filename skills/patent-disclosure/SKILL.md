---
name: patent-disclosure
description: "Draft an evidence-grounded invention disclosure, claim skeleton, prior-art plan, and figure plan."
argument-hint: [invention-topic]
allowed-tools: Bash(*), Read, Write, Edit, Grep, Glob
---

# 专利交底书

根据当前项目中的真实技术材料形成专利交底草稿：**$ARGUMENTS**

## 必须输出

- `patent/INVENTION_DISCLOSURE.md`：技术问题、现有方案不足、技术方案、实施方式、可验证效果和边界。
- `patent/CLAIMS_DRAFT.md`：独立权利要求骨架与从属特征候选，逐项关联交底书段落。
- `patent/PRIOR_ART_PLAN.md`：检索关键词、分类号候选、数据库和需要核验的近似方案，不虚构公开号。
- `patent/FIGURE_PLAN.md`：附图编号、对象、关系、数据来源和待绘制清单。

## 规则

- 先扫描 `user_data/`、代码、实验记录和现有图；事实必须能定位到文件。
- 未有证据的技术效果不得写成已证实结论。
- 区分核心必要特征、可选特征与实施例，不把论文式性能宣传写进权利要求。
- 不输出授权概率或法律意见；所有内容均标为申请人和代理师复核草稿。
- 使用 `Write` 真正创建四个文件。

结束前执行：

```bash
test -s patent/INVENTION_DISCLOSURE.md && test -s patent/CLAIMS_DRAFT.md && test -s patent/PRIOR_ART_PLAN.md && test -s patent/FIGURE_PLAN.md
```

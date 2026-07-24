---
name: project-blueprint
description: "Turn one research sentence into an auditable project blueprint, research-contract draft, and milestone plan."
argument-hint: [one-sentence-project-idea]
allowed-tools: Bash(*), Read, Write, Edit, Grep, Glob
---

# 一句话生成研究项目

根据用户的一句话构想生成可执行研究项目：**$ARGUMENTS**

## 必须输出

1. `PROJECT_BLUEPRINT.md`：问题、研究空白、对象、变量、机制、方法、风险和预期贡献。
2. `RESEARCH_CONTRACT_DRAFT.md`：研究问题、纳入/排除标准、证据边界、验证标准、人工审批点。
3. `MILESTONES.md`：按阶段列出输入、任务、可验证产物、完成条件和失败恢复动作。

## 规则

- 不得把一句话扩写成未经核验的事实；未知内容必须标为待确认。
- 每项预期结论必须对应可观测证据或实验。
- 明确列出竞争性解释、适用边界和最低可行实验。
- 不虚构参考文献、数据、模型效果、时间或预算。
- 使用 `Write` 真正写出三个文件，不能只在回复中展示。

结束前执行：

```bash
test -s PROJECT_BLUEPRINT.md && test -s RESEARCH_CONTRACT_DRAFT.md && test -s MILESTONES.md
```

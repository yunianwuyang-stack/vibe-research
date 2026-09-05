# 评价/决策类自检（TOPSIS/AHP/熵权法/排名打分必读）

## 专项检查清单

```
E1. [权重归一] 权重之和是否等于 1（误差 ≤ 0.01）？
E2. [一致性] AHP 的 CR < 0.1？（如果用了 AHP）
E3. [排名稳定] 权重微调后排名是否稳定？
E4. [指标方向] 正向/负向指标是否正确处理？
E5. [得分区分度] 所有方案得分差异是否 < 1%（无区分度）？
E6. [常识对照] 排名是否与题目暗示的常识严重矛盾（正负向反了）？
E7. [熵权法 log(0)] 归一化后是否有 p_ij = 0？必须用 p_ij·ln(p_ij) 在 p=0 处取 0（或加极小平移），
    否则出现 nan 权重；某指标所有方案取值相同 → 该指标熵=1、权重=0，需在报告中说明而不是静默丢弃
E8. [TOPSIS 负向指标] 负向/区间型指标必须先正向化再归一化；理想解 z+ 取的是"正向化后"的列最大值
E9. [AHP RI 表] n≥3 才算 CR；RI 用标准表 {3:0.58, 4:0.90, 5:1.12, 6:1.24, 7:1.32, 8:1.41, 9:1.45}，
    n=1,2 时 CR 恒为 0 不必报告
E10. [归一化零除] 极差归一化 (x-min)/(max-min) 在 max==min 时零除 → 必须显式处理
E11. [权重来源] 主观权重（AHP）与客观权重（熵权/CRITIC）组合时，组合方式（乘积归一/加权平均）必须写明
```

## 红旗信号

| 现象 | 可能原因 |
|------|---------|
| 权重之和 ≠ 1（误差 > 0.01） | 归一化步骤遗漏 |
| 所有方案得分差异 < 1% | 指标选择不当 / 权重过于均匀 |
| 排名与题目暗示的常识严重矛盾 | 正负向指标处理反了 |
| AHP CR > 0.1 | 判断矩阵不一致, 需修正 |

## 权重稳定性验证

```python
# 微调权重 ±10%, 看排名是否稳定（⛔ 必须固定 seed，否则每次跑结论不同、论文无法复现）
import numpy as np
rng = np.random.default_rng(42)
base_weights = np.array([0.3, 0.25, 0.2, 0.15, 0.1])
assert abs(base_weights.sum() - 1) < 1e-6, "权重未归一"
base_rank = compute_rank(base_weights)

shaken_ranks = []
for trial in range(200):   # 20 次太少，Spearman/Kendall 统计不稳定；200 次足够且很快
    perturb = 1 + rng.uniform(-0.1, 0.1, len(base_weights))
    w = base_weights * perturb
    w /= w.sum()
    shaken_ranks.append(compute_rank(w))

# 计算每个方案的排名变化范围
import collections
for idx in range(num_alternatives):
    ranks_at_idx = [r[idx] for r in shaken_ranks]
    span = max(ranks_at_idx) - min(ranks_at_idx)
    if span > 2:
        print(f"⚠ 方案 {idx} 排名波动 {span} 名, 不稳定")

# 整体稳定性用秩相关系数量化（写进 results.json，供论文引用）
from scipy.stats import spearmanr
rhos = [spearmanr(base_rank, r).correlation for r in shaken_ranks]
print(f"Spearman ρ 均值={np.mean(rhos):.3f}, 最小={np.min(rhos):.3f}（>0.9 视为稳定）")
```

## 必产数据

```json
{
  "method": "TOPSIS / AHP / 熵权法",
  "weights": {"指标1": 0.3, "指标2": 0.25, ...},
  "weights_sum": 1.0,
  "ahp_cr": 0.08,
  "scores": {"方案A": 0.85, "方案B": 0.72, ...},
  "ranking": ["方案A", "方案B", "方案C"],
  "stability": {"weight_perturb_pct": 10, "max_rank_change": 1}
}
```

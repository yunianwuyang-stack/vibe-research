# 常用建模方法参考表

> 选方法的顺序：**能精确求解就精确求解**（LP/MILP/凸问题），精确不可行（规模/非凸/黑箱）再用启发式；
> 启发式必须给出基准解与多种子稳定性。表中"首选"栏是 2024+ 的主流开源选择。

| 问题类型 | 常用方法 | Python 库（首选 → 备选） | 备注 |
|----------|----------|-----------|------|
| 线性规划 | 单纯形法、内点法 | `scipy.optimize.linprog(method="highs")` → PuLP(HiGHS/CBC) | HiGHS 已内置于 SciPy ≥1.9，速度远超旧 simplex |
| 整数/混合整数规划 | 分支定界、割平面 | PuLP(CBC/HiGHS) → OR-Tools **CP-SAT**（组合/调度尤佳）→ SCIP(pyscipopt) | 报告 MIP gap；CP-SAT 对排程/指派/时间窗类通常更快 |
| 非线性优化（连续） | SLSQP / trust-constr / L-BFGS-B | `scipy.optimize.minimize` → cvxpy（凸问题）→ pyomo+ipopt | 非凸必须 multistart；凸问题优先 cvxpy 保证全局最优 |
| 全局/黑箱优化 | 差分进化、CMA-ES、贝叶斯优化 | `scipy.optimize.differential_evolution` → `cma` → `optuna` | 必须固定 seed、报告多次运行 CV |
| 多目标优化 | NSGA-II/III、加权法、ε-约束 | pymoo → platypus | 输出 Pareto 前沿 + 超体积指标 |
| 组合优化（TSP/VRP/排程） | 贪心构造 + 2-opt/Or-opt、LNS、CP-SAT | OR-Tools routing / CP-SAT → python-tsp / LKH | 小规模 (<15 城) 可精确 MILP 验证启发式 |
| 回归分析 | OLS、岭/LASSO、GLM、分位数回归 | statsmodels（报告 p 值/CI/诊断）→ sklearn | 因果解释必须写清识别策略 |
| 时间序列 | ARIMA/SARIMA、ETS、Prophet、LSTM/TCN | statsmodels / pmdarima → prophet → torch | 必须用滚动/时序切分，禁止随机 KFold |
| 机器学习预测 | 梯度提升树、随机森林、SHAP 解释 | lightgbm / xgboost → sklearn；shap | 交叉验证 + 特征重要性 + 校准 |
| 聚类分析 | K-means(++)、DBSCAN/HDBSCAN、层次聚类、GMM | sklearn → hdbscan | 报告轮廓系数/CH 指标选 k |
| 层次分析 (AHP) | 判断矩阵 + 一致性检验 | 手动实现 / ahpy | n≥3 才报 CR，CR<0.1 |
| 综合评价 | TOPSIS、熵权法、CRITIC、灰色关联、DEA | 手动实现 / pyDEA | 负向指标先正向化；熵权 log(0) 处理 |
| 灰色预测 | GM(1,1)、GM(1,N) | 手动实现 | 只适合小样本、近似指数趋势；必须做后验差检验 |
| 图论 | Dijkstra、Floyd、最大流/最小费用流、最小生成树 | networkx → igraph（大图） | 大图用 igraph/scipy.sparse.csgraph |
| 蒙特卡洛 / 随机模拟 | 逆变换、重要性采样、拉丁超立方 | `numpy.random.default_rng(seed)` → scipy.stats.qmc | 报告样本数与置信区间 |
| 微分方程 | RK45/LSODA/Radau（刚性）、有限差分 | `scipy.integrate.solve_ivp` → fipy/fenics(PDE) | 刚性问题选 Radau/BDF；结果必须做物理约束检验 |
| 参数估计 / 贝叶斯 | MLE、MCMC | scipy.optimize → pymc / emcee | 多链 R̂<1.1 |
| 排队/仿真 | M/M/c 公式、离散事件仿真 | 手动 / simpy | 仿真需热身期 + 多次重复 |
| 传染病/生态动力学 | SIR/SEIR、Lotka-Volterra | solve_ivp + 参数拟合 (least_squares) | 时变参数不能取均值当常数 |
| 空间/地理 | K-D 树、Voronoi、凸包、覆盖优化 | scipy.spatial → shapely / geopandas | 距离用大圆/投影坐标，勿直接用经纬度欧氏距离 |

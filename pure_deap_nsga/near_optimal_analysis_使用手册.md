# M3 近优分析（near_optimal_analysis.py）工作总结与使用手册

生成日期：2026-05-20 | 状态：已完成

---

## 1. 工作概述

`near_optimal_analysis.py`（~580行）是 Part II "近优设计分析" 的核心脚本，完成以下全流程：

```
全局Pareto汇聚 → 3D非支配排序 → 冲突度量（Spearman + Pay-off）
→ 维度缩减判断 → 近优区域定义 → 参数CV分类 → 构型/工质竞争
→ 代表设计选取 → 可视化出图
```

**输入：** `results/pareto_{WP}_*.csv`（由 `run_optimization.py` 生成）  
**输出：** 每工况3张图 + 2张CSV数据表；跨工况3张对比图 + 1张汇总表

---

## 2. 使用方法

### 2.1 单工况分析

```bash
cd pure_deap_nsga
python3 near_optimal_analysis.py --wp DC-A
```

### 2.2 自定义阈值

```bash
python3 near_optimal_analysis.py --wp DC-A \
    --top-frac 0.15      # 近优比例（默认0.10，即top-10%）
    --cv-low 0.08        # must-have CV上限（默认0.10）
    --cv-high 0.25       # real-choice CV下限（默认0.20）
```

### 2.3 跨工况对比

```bash
python3 near_optimal_analysis.py --compare DC-A DC-C DC-E
```

### 2.4 参数说明

| 参数 | 默认值 | 含义 |
|------|--------|------|
| `--wp` | （必填） | 单个工况名，如 DC-A |
| `--compare` | — | 多个工况名，如 `DC-A DC-C DC-E`（与 `--wp` 互斥） |
| `--top-frac` | 0.10 | 近优区域比例（按 utopia 距离截断） |
| `--cv-low` | 0.10 | must-have 分类的 CV 上限 |
| `--cv-high` | 0.20 | real-choice 分类的 CV 下限 |

---

## 3. 分析方法说明

### 3.1 近优区域定义

采用 **utopia点距离法**（而非独立分位数交集法）。对全局 Pareto 前沿上的每个解：

1. 将 η_p2p 和 e_th 归一化到 [0, 1]
2. 计算到理想点 (1, 1) 的欧氏距离
3. 选取距离最小的 top-10% 作为近优子集

**设计原因：** η_p2p 与 e_th 强冲突（r_s ≈ -0.85 ~ -0.99），独立分位数交集会产生零个解（不存在同时满足两个分位数的点）。

### 3.2 维度缩减判断

```
2-obj 成立条件: C_p2p_ex < 0.55  AND  r_s(p2p, ex) > -0.5
3-obj 需要条件: C_p2p_ex ≥ 0.55  OR   r_s(p2p, ex) ≤ -0.5
```

**逻辑：** 强正相关（r_s > 0.5）表示 η_ex 与 η_p2p 对齐 → 维度缩减更合理，η_ex 不提供冲突信息；强负相关表示存在真实 trade-off → 需保留。

### 3.3 参数 CV 分类

对近优子集中每个决策变量的变异系数：

| 分类 | CV 范围 | 含义 |
|------|---------|------|
| must-have | CV < 0.10 | 近优区高度稳定，设计时优先锁定 |
| gray | 0.10 ≤ CV ≤ 0.20 | 过渡区，有调节余量但不大 |
| real-choice | CV > 0.20 | 近优区内跨越大，代表真正的设计选择 |

### 3.4 代表设计选取

- **D_eff**：max η_p2p（效率导向）
- **D_den**：max e_th（密度导向）
- **D_bal**：归一化空间中最接近理想点（膝点，平衡设计）

---

## 4. 输出文件清单

### 4.1 图表（plots/near_optimal/）

| 文件 | 对应论文图号 | 内容 |
|------|-------------|------|
| `near_optimal_region_{WP}.png` | Fig 6 | 3-panel：全局前沿、η_p2p–η_ex 投影、e_th–η_ex 投影；标注代表设计和维度缩减结论 |
| `parameter_violins_{WP}.png` | Fig 7 | 2×5 小提琴图，按 CV 升序排列，颜色标注分类 |
| `config_competition_{WP}.png` | Fig 8 | 左：构型占比（GF vs 近优）| 右：工质对在近优中分布 |
| `cross_wp_cv_comparison.png` | Fig 9a | 三工况 CV 分组条形图 |
| `cross_wp_config_comparison.png` | Fig 9b | 三工况构型占比并列对比 |
| `dimension_reduction_landscape.png` | Fig 9c | 6-WP 维度缩减景观（C vs r_s 散点） |

### 4.2 数据表（results/）

| 文件 | 内容 |
|------|------|
| `near_optimal_{WP}_params.csv` | 参数 CV、均值、std、分类 |
| `near_optimal_{WP}_designs.csv` | D_eff/D_den/D_bal 完整设计参数 |
| `near_optimal_cross_wp_summary.csv` | 6-WP 汇总：冲突度量、维度缩减判定、近优区范围 |

---

## 5. 核心发现

### 5.1 维度缩减景观

| 冷却方式 | 工况 | C_p2p_ex | r_s(p2p, ex) | 维度缩减 |
|---------|------|----------|-------------|---------|
| 风冷 (35°C) | DC-A/B | 0.44 / 0.34 | +0.41 / +0.74 | **2-obj OK** |
| 液冷 (45°C) | DC-C | 0.66 | +0.02 | 3-obj 需要 |
| 液冷 (45°C) | DC-D | 0.46 | +0.40 | **2-obj OK** |
| HPC (60°C) | DC-E/F | 0.63 / 0.66 | -0.24 / -0.19 | 3-obj 需要 |

**→ 验证 Li et al. (2024) 60°C 阈值：** 废热温度超过 60°C 后，η_p2p–η_ex 冲突恢复，需保留三目标框架。

### 5.2 构型竞争

- SRVCHP_SRORC 占近优 60–93%，是全工况主导构型
- SBVCHP 系列在所有工况近优中被淘汰
- SRVCHP_SBORC 仅在 HPC 工况存活（DC-E 32%, DC-F 41%）

### 5.3 参数普适性

- **跨工况 must-have：** η_max_cp, η_max_ex, η_pm, T_st_ht（CV < 0.03）
- **跨工况 real-choice：** dT_hp_cs_gl（CV 0.53–0.75）
- **冷却等级升高趋势：** dT_he_ev_sh 和 dT_hp_ev_sh 从 gray → real-choice

---

## 6. 依赖与运行环境

```bash
conda activate oemof-heat-pump-tutorial-env
# 或
/opt/homebrew/anaconda3/envs/oemof-heat-pump-tutorial-env/bin/python near_optimal_analysis.py --wp DC-A
```

**核心依赖：** numpy, pandas, matplotlib, scipy（均已在该 conda 环境中安装）

**前置条件：** `results/` 目录下存在至少一个 `pareto_{WP}_*.csv` 文件（运行 `run_optimization.py` 后自动生成）。

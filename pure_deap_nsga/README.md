# DEAP-based NSGA Optimizer for Carnot Battery Systems

基于DEAP库的卡诺电池系统多目标优化框架，直接实现NSGA-II/NSGA-III算法，无需RHEIA中间层。

## 核心特性

### 1. 优化算法
- **NSGA-II**: 经典的多目标进化算法，适用于2-3个目标
- **NSGA-III**: 基于参考点的算法，适用于4个以上目标
- 使用DEAP库实现，支持SBX交叉和多项式变异

### 2. 决策变量（9个连续变量）
- `T_st_ht`: 热储罐温度 [°C]
- `dT_st_sp`: 储罐温度跨度 [K]
- `dT_hp_cs_gl`: 热泵冷源温度滑移 [K]
- `dT_hp_ev_sh`: 热泵蒸发器过热度 [K]
- `dT_he_ev_sh`: 热机蒸发器过热度 [K]
- `dT_hp_cd_sc`: 热泵冷凝器过冷度 [K]
- `eta_max_cp`: 压缩机等熵效率 [-]
- `eta_max_ex`: 膨胀机等熵效率 [-]
- `eta_pm`: 泵/电机机械效率 [-]

### 3. 热力学约束
- CB求解器必须收敛（`error=False`）
- 不可行解通过大负值惩罚处理
- 自动过滤热力学不合理的解

### 4. 优化目标

#### 热力学目标（已实现）
1. **eta_p2p**: 往返效率 η_P2P = η_HP × η_HE
2. **energy_density_thermal**: 热能密度 [kWh/m³]
3. **exergy_efficiency**: 㶲效率 η_II
4. **energy_density_electric**: 电能密度 [kWh_el/m³]
5. **cop_hp**: 热泵COP
6. **eta_he**: 热机热效率
7. **carnot_ratio**: 实际效率与卡诺效率之比
8. **storage_exergy_density**: 储能㶲密度 [kWh_ex/m³]
9. **neg_storage_volume**: 负储罐体积（最小化体积）

#### 经济性目标（接口已实现）
10. **neg_lcos**: 负平准化储能成本 [$/kWh] - 最小化LCOS
11. **neg_specific_capex**: 负单位容量投资 [$/kWh] - 最小化单位成本

经济性目标需要在配置文件中提供`economic_params`：
```json
"economic_params": {
  "capex_hp_per_kw": 800.0,        // 热泵投资 [$/kW]
  "capex_he_per_kw": 1200.0,       // 热机投资 [$/kW]
  "capex_storage_per_m3": 50.0,    // 储罐投资 [$/m³]
  "opex_fraction": 0.02,           // 年运维成本占CAPEX比例
  "lifetime_years": 20,            // 系统寿命 [年]
  "cycles_per_year": 250,          // 年循环次数
  "discount_rate": 0.05            // 贴现率
}
```

## 文件结构

```
pure_deap_nsga/
├── deap_optimizer.py          # 核心优化器模块
├── run_optimization.py        # 主运行脚本
├── optimization_config.json   # 优化配置文件
├── test_optimizer.py          # 单元测试脚本
├── README.md                  # 本文档
└── results/                   # 优化结果输出目录
    ├── pareto_*.csv          # 各工况帕累托前沿
    └── all_pareto_combined.csv # 所有结果汇总
```

## 使用方法

### 1. 基本用法

运行所有工况和配置的优化：
```bash
cd /home/oxford/CBSim_of_DC/pure_deap_nsga
python3 run_optimization.py --verbose
```

### 2. 单个工况优化

只优化特定数据中心工况：
```bash
python3 run_optimization.py --wp DC-A --verbose
```

### 3. 单个配置优化

只优化特定CB配置：
```bash
python3 run_optimization.py --cfg SBVCHP_SBORC --verbose
```

### 4. 组合使用

优化特定工况和配置的组合：
```bash
python3 run_optimization.py --wp DC-C --cfg SRVCHP_SRORC --seed 123 --verbose
```

### 5. 自定义配置文件

使用自定义配置：
```bash
python3 run_optimization.py --config my_config.json
```

## 配置文件说明

### 工作点定义
```json
"working_points": {
  "DC-A": {
    "T_hs": 35.0,              // 热源温度 [°C]
    "T_cs": 5.0,               // 冷源温度 [°C]
    "T_st_ht_min": 50.0,       // 热储罐最低温度 [°C]
    "T_st_ht_max": 120.0,      // 热储罐最高温度 [°C]
    "dT_st_sp_min": 15.0,      // 最小温度跨度 [K]
    "dT_st_sp_max": 60.0       // 最大温度跨度 [K]
  }
}
```

### CB配置定义
```json
"configurations": {
  "SBVCHP_SBORC": {
    "class": "SBVCHP_SBORC_STES2T",  // CBSim类名
    "has_hp_regenerator": false,      // 热泵是否有回热器
    "has_he_regenerator": false       // 热机是否有回热器
  }
}
```

### 优化设置
```json
"optimization": {
  "algorithm": "NSGA2",              // NSGA2 或 NSGA3
  "population_size": 100,            // 种群大小
  "n_generations": 150,              // 迭代代数
  "crossover_prob": 0.9,             // 交叉概率
  "mutation_prob": 0.1,              // 变异概率
  "seed": 42,                        // 随机种子
  "objectives": [                    // 优化目标列表
    "eta_p2p",
    "energy_density_thermal",
    "exergy_efficiency"
  ]
}
```

## 与现有方法的对比

### 原方法（LHS + 非支配排序）
- **优点**: 稳定，不依赖梯度，适合黑盒优化
- **缺点**: 采样效率低，需要大量样本才能逼近帕累托前沿

### DEAP方法（NSGA-II/III）
- **优点**:
  - 进化算法，自适应搜索帕累托前沿
  - 种群规模小，计算效率高
  - 支持多目标（3个以上）优化
  - 可扩展性强，易于添加新目标
- **缺点**:
  - 需要调参（交叉/变异概率）
  - 对初始种群敏感

## 新增优化目标说明

### 1. carnot_ratio（卡诺效率比）
衡量系统接近热力学理想的程度：
```
carnot_ratio = η_P2P / η_Carnot
其中 η_Carnot = 1 - T_lt/T_ht
```
该指标越接近1，说明系统越接近理想卡诺循环。

### 2. storage_exergy_density（储能㶲密度）
考虑储能质量的密度指标：
```
ex_density = (i_ht - i_lt) - T_0*(s_ht - s_lt)
```
㶲密度比能量密度更能反映储能的实际价值。

### 3. neg_storage_volume（负储罐体积）
最小化储罐体积，适用于空间受限场景。

### 4. neg_lcos（负平准化储能成本）
综合考虑投资、运维和能量吞吐的经济性指标：
```
LCOS = (CAPEX × CRF + OPEX_annual) / E_annual
```
其中CRF为资本回收因子，考虑了贴现率和系统寿命。

## 扩展开发指南

### 添加新的优化目标

1. 在`deap_optimizer.py`的`Objectives`类中添加新方法：
```python
@staticmethod
def my_new_objective(cb) -> float:
    """新目标函数说明"""
    if cb.error:
        return INFEASIBLE_PENALTY
    # 计算目标值
    value = ...
    return value  # 返回值用于最大化
```

2. 在`OBJECTIVE_MAP`中注册：
```python
OBJECTIVE_MAP = {
    ...
    'my_new_objective': Objectives.my_new_objective,
}
```

3. 在配置文件中使用：
```json
"objectives": ["eta_p2p", "my_new_objective"]
```

### 添加新的CB配置

在配置文件中添加新的配置类：
```json
"configurations": {
  "MY_NEW_CONFIG": {
    "class": "MY_CB_CLASS_NAME",
    "has_hp_regenerator": true,
    "has_he_regenerator": true
  }
}
```

## 依赖项

```bash
pip install deap numpy pandas scipy CoolProp matplotlib
```

## 性能建议

1. **种群大小**: 100-200适合3目标优化，200-300适合4+目标
2. **迭代代数**: 100-200代通常足够收敛
3. **并行化**: 可修改代码使用`multiprocessing`并行评估个体
4. **预筛选**: 在评估前进行简单的可行性检查，减少无效计算

## 输出结果

每个优化任务生成一个CSV文件，包含：
- 决策变量值（9个）
- 目标函数值（用户指定的目标）
- 工况和配置信息（wp, cb_config, fluid_hp, fluid_he）

结果可用于：
- 帕累托前沿可视化
- 配置优势分析
- 全局非支配排序
- 决策支持

## 许可证

本项目为CBSim项目的一部分，遵循相同的许可证。

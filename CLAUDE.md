# CLAUDE.md — CBSim 卡诺电池仿真优化项目总览

## 项目定位

CBSim 是一个面向数据中心废热回收的卡诺电池（Carnot Battery）热力学仿真与多目标优化系统。核心任务：蒸气压缩热泵（HP）+ 双罐感热储能（STES-2T）+ 有机朗肯循环（ORC）的稳态建模 → NSGA-II 三目标优化 → 全局前沿近优分析 → off-design 鲁棒性评估。最终产出为一篇三部分结构的期刊论文（目标期刊：*Applied Thermal Engineering* / *Energy Conversion and Management*）。

**数值模型来源**：CBSim 库（Author: Antoine Laterre, March 2025），本项目在其基础上增加了 DEAP 优化层、六工况分析框架、近优分析模块和 off-design 评估模块。

## Python 环境

**激活环境（macOS）：** `oemof-heat-pump-tutorial-env` conda 环境。

```bash
/opt/homebrew/anaconda3/envs/oemof-heat-pump-tutorial-env/bin/python <script.py>
# 或先 conda activate oemof-heat-pump-tutorial-env
```

**关键约束：** `scipy` 必须 `<1.12`。scipy ≥ 1.12 导致 CoolProp `AbstractState.update()` 在 `fsolve`/`least_squares` 中抛出 `TypeError: only 0-dimensional arrays can be converted to Python scalars`。

**备选 uv 安装：**
```bash
uv venv .venv --python 3.11
uv pip install --python .venv/bin/python "scipy==1.11.4"
uv pip install --python .venv/bin/python -e . --no-deps
source .venv/bin/activate
```

## 目录树与文件职责

```
Carnot_Battery_for_DC/
├── src/                                    # [建模工程师] CBSim 热力学核心（不改，除非修复收敛问题）
│   ├── _module_carnot_battery.py           # 4 种构型类：SBVCHP_SBORC_STES2T, SBVCHP_SRORC_STES2T, SRVCHP_SBORC_STES2T, SRVCHP_SRORC_STES2T
│   ├── _module_heat_pump.py               # HP 循环求解器（CoolProp + fsolve，~144KB）
│   ├── _module_heat_engine.py             # ORC 循环求解器（CoolProp + fsolve，~126KB）
│   └── _module_plots.py                   # CBSim 内置绘图（~58KB）
│
├── pure_deap_nsga/                         # [优化设计师] 主工作区：优化 + 分析 + 绘图
│   ├── optimization_config.json            # [构型设计师] 唯一配置源：WP/构型/工质/算法参数
│   ├── deap_optimizer.py                   # [优化设计师] 核心：Objectives + CBEvaluator + NSGAOptimizer
│   ├── run_optimization.py                 # [优化设计师] CLI 入口：批量 NSGA-II 运行
│   ├── test_optimizer.py                   # [验收测试] 4 项单元测试
│   ├── build_global_pareto.py              # [优化设计师] 全局 Pareto 构建 + ΔT_sp 中介分析 + 降维判断
│   ├── analyze_conflict.py                 # [优化设计师] 三目标冲突指标（Spearman / C_ij / d_Euclidean）
│   ├── near_optimal_analysis.py            # [优化设计师] Part II：近优空间参数分布 + must-have/real-choice + 代表设计
│   ├── off_design_eval.py                  # [优化设计师] Part III：季节对 off-design 鲁棒性评估
│   ├── plot_pareto_pairwise.py             # [优化设计师] 成对 Pareto 散点图（含目标排名着色）
│   ├── plot_pareto_single.py               # [优化设计师] 单个 Pareto 前沿可视化
│   ├── plot_config_decomposition.py        # [优化设计师] 按构型分解的 Pareto 前沿
│   ├── plot_six_wp_evolution.py            # [优化设计师] 六工况冲突强度演化图（Fig 3.3）
│   ├── verify_H1.py ~ verify_H5.py         # [建模工程师] 5 个假设验证脚本（DC-A 冲突机制）
│   ├── results/                            # [调用计算员] 输出：~198 个 CSV（每工况×构型×工质对的 Pareto 前沿）
│   │   ├── pareto_{WP}_{CFG}_{HP}_{HE}.csv # 单次优化结果
│   │   ├── all_pareto_combined.csv         # 全部结果汇总
│   │   ├── near_optimal_{WP}_params.csv    # 近优参数分类
│   │   ├── near_optimal_{WP}_designs.csv   # 代表设计参数
│   │   ├── near_optimal_cross_wp_summary.csv
│   │   ├── off_design_eval.csv
│   │   └── off_design_retention.csv
│   ├── plots/                              # [优化设计师] 输出图表
│   ├── reports/                            # [优化设计师] 分析报告
│   ├── _archive/                           # 已废弃脚本（8 个 Per-WP 绘图 + build_presentation.py）
│   └── README.md                           # DEAP 优化器使用手册（中文）
│
├── simulation_notes/                        # [建模工程师] 仿真笔记：参数扫描、Zhang2020 复现等
│   ├── dc_pareto_scan.py                   # LHS 扫描脚本（早期方法，已被 DEAP 取代）
│   ├── pareto_frontier_scan.py             # 前沿扫描脚本
│   ├── plot_shaft_zhang2020_v2.py          # Zhang 2020 转速调节复现
│   ├── dc_config.json                      # 早期配置文件
│   ├── _batch_eval.py                      # 批量评估辅助
│   └── figs/ + results/                    # 笔记专属图表和结果
│
├── opt/                                     # [优化设计师] 外部优化框架（参考，非主用）
│   ├── RHEIA/                              # RHEIA 优化框架（build/lib 结构，本项目未直接使用）
│   └── multi_objective_optimization_reproduce/ # 4 个 position 的 LHS 复现脚本
│
├── paper/                                   # [文献阅读员] 论文写作与文献管理
│   ├── 期刊论文初稿大纲（v3.0）.md          # 当前版本大纲：三部分结构，12 张图表规划，三层 Laterre 对话
│   ├── 期刊论文初稿大纲（v2.0）.md          # 旧版（Lorenz/CSDW 路线，已放弃）
│   ├── 文献锚定方案_M2.md                   # [文献阅读员] 11 篇核心文献的仿真设计决策锚定
│   ├── 待获取文献清单.md                    # 待获取文献追踪
│   ├── 技术报告：面向数据中心废热回收的卡诺电池系统建模、优化与动态性能分析.md
│   ├── Laterre_2024_*.md / Latette_2024_*.md # [文献阅读员] Laterre 系列文献笔记
│   ├── model_validation_plan.md             # 模型验证方案
│   ├── Li 等 - 2024 - .../                 # Li 2024 论文目录（含 PDF + 笔记）
│   ├── Laterre - 2025 - .../               # Laterre 博士论文目录
│   ├── Laterre 等 - 2024 - .../            # Laterre 2024 Energy 论文
│   └── Laterre 等 - 2026 - .../            # Laterre 2026 ECM 论文
│
├── figs/                                    # 项目级图表（PPT 用）
├── main_cb.py / main_hp.py / main_he.py     # CBSim 独立运行示例
├── pyproject.toml                           # Python 包配置 + 依赖声明
├── test_mac_coolprop.py                     # macOS CoolProp 兼容性测试
├── small_work_presentation.md               # 组会 PPT 大纲
└── README_ENV.md                            # 环境配置说明
```

## 项目 Agent 体系

本项目采用 **7 角色 Agent 协作体系**，每个角色有不同的职责边界和调用时机：

### Agent 1：构型设计师（Configuration Designer）
**负责**：热力学循环构型设计、工质选择策略、工作点定义、`optimization_config.json` 维护。
**能力域**：构型命名规则（SB/SR + VCHP/ORC）、工质临界温度筛选准则（T_crit > T_max + 20K）、ΔT 区间与构型竞争优势的关系、Li 2024 的 60°C 阈值对构型选择的影响。
**不负责**：数值建模实现、优化算法。
**调用时机**：新增/修改 CB 构型、添加工质、调整工作点边界约束、讨论构型竞争关系时。

### Agent 2：建模工程师（Modeling Engineer）
**负责**：`src/` 下 CBSim 热力学核心的维护、仿真模型 API 管理、求解器收敛问题的诊断和修复。
**能力域**：CoolProp 调用链、`fsolve` 收敛逻辑、HP/ORC 循环方程、`_module_carnot_battery.py` 的 14 元素输入元组接口、CB 类的 `inputs/params/options` 三层参数结构。
**不负责**：优化算法设计、文献分析。
**调用时机**：修改 `src/` 下任何文件、新增构型类、诊断求解失败、修复收敛 bug、分析仿真输出异常时。

### Agent 3：优化设计师（Optimization Designer）
**负责**：DEAP 优化算法开发、目标函数设计、`deap_optimizer.py` 和 `run_optimization.py` 维护、分析脚本（`build_global_pareto.py`, `analyze_conflict.py`, `near_optimal_analysis.py`, `off_design_eval.py`）开发、绘图脚本维护。
**能力域**：NSGA-II/III 算法、SBX 交叉 + 多项式变异、9 维决策变量编码、11 个目标函数的数学定义、不可行解惩罚策略、Pareto 前沿非支配排序、冲突指标（Spearman/C_ij/d_Euclidean）、近优分析（must-have/real-choice）、off-design 评估方法。
**不负责**：CBSim 热力学核心修改、文献参数提取。
**调用时机**：修改优化算法参数、新增/调整目标函数、运行优化、开发分析脚本、生成图表时。

### Agent 4：文献阅读员（Literature Reader）
**负责**：提取文献信息、维护文献参数配置表、管理 `文献锚定方案_M2.md`、更新 `期刊论文初稿大纲`、追踪待获取文献。
**能力域**：11 篇核心文献（Laterre×3, Dumont & Lemort 2020, Li 2024, Yuan 2025, ASHRAE TC9.9, Frate 2019, Deb 2002, McTigue 2024, Poletto 2025）、每个仿真设计决策的文献依据链、Li 2024 的 60°C 阈值映射、Laterre 三元悖论框架。
**不负责**：任何编程/建模/优化工作。只管理文献信息。
**调用时机**：查找文献依据、更新论文大纲、锚定设计决策、管理参考文献列表、讨论研究空白和贡献定位时。

### Agent 5：验收测试（Acceptance Tester）
**负责**：运行 `test_optimizer.py`、验证优化结果可复现性、检查输出文件完整性、报告测试通过/失败状态。
**能力域**：4 项测试覆盖（目标注册、CBEvaluator 单点、NSGA-II 快速运行、配置加载）、结果文件行数/列数完整性检查。
**不负责**：修复 bug（交由 Bug 反馈工程师 + 建模工程师协同）。
**调用时机**：任何代码修改后、运行优化前、提交前检查、用户要求验证时。

### Agent 6：调用计算员（Computation Runner）
**负责**：接收仿真优化执行方案并执行、记录执行结果（日志 + 输出文件路径）、报告计算耗时和收敛统计。
**能力域**：`run_optimization.py` 的 CLI 接口（--wp / --cfg / --seed / --verbose）、`near_optimal_analysis.py` 和 `off_design_eval.py` 的命令行调用、日志解析。
**不负责**：修改代码、分析结果含义、诊断错误（遇到错误转发给 Bug 反馈工程师）。
**调用时机**：需要批量运行优化、执行近优分析、运行 off-design 评估时。

### Agent 7：Bug 反馈工程师（Bug Feedback Engineer）
**负责**：接收报错信息并分析、定位错误来源（CBSim 核心 vs 优化层 vs 数据层）、与建模工程师协同排错。
**能力域**：Python traceback 解析、CoolProp 常见错误（`TypeError: only 0-dimensional arrays` → scipy ≥ 1.12）、CBSim `error=True` 的诊断（收敛失败 vs 热力学不可行）、DEAP 的 `Fitness` 类错误。
**不负责**：直接修改代码（诊断后交由对应工程师修改）。
**调用时机**：任何脚本报错、优化结果异常（无可行为解、目标值为 INFEASIBLE_PENALTY）、收敛失败时。

### Agent 协作流程

```
                    ┌──────────────┐
                    │  文献阅读员   │ ← 提供文献依据、参数范围
                    └──────┬───────┘
                           │
              ┌────────────┼────────────┐
              ▼            ▼            ▼
      ┌───────────┐ ┌───────────┐ ┌───────────┐
      │ 构型设计师 │ │ 建模工程师 │ │ 优化设计师 │
      └─────┬─────┘ └─────┬─────┘ └─────┬─────┘
            │              │              │
            └──────────────┼──────────────┘
                           │ optimization_config.json
                           ▼
                    ┌──────────────┐
                    │  调用计算员   │ ← 执行仿真优化
                    └──────┬───────┘
                           │
                     ┌─────┴─────┐
                     ▼            ▼
              ┌───────────┐ ┌───────────┐
              │ 验收测试   │ │Bug反馈工程师│
              └───────────┘ └─────┬─────┘
                                  │
                                  ▼
                           ┌───────────┐
                           │ 建模工程师 │ ← 协同排错
                           └───────────┘
```

## 核心数据流

```
optimization_config.json               ← 构型设计师 + 优化设计师维护
        │
        ▼
run_optimization.py                    ← 调用计算员执行
  for each (WP × Config × Fluid combo):
        │
        ▼
NSGAOptimizer (deap_optimizer.py)      ← 优化设计师维护
  DEAP NSGA-II loop (pop=100, gen=150)
  SBX crossover (eta=20) + Poly mutation (eta=20)
        │ evaluates each individual (9-D vector x)
        ▼
CBEvaluator.evaluate(x[0..8])          ← 优化设计师维护
  builds CBSim inputs (14-element tuple) + params (dict) + options
        │
        ▼
src/_module_carnot_battery.py          ← 建模工程师维护
  {Config}_STES2T.evaluate()
  ├── _module_heat_pump.py             ← HP 求解 (CoolProp + fsolve)
  └── _module_heat_engine.py           ← ORC 求解 (CoolProp + fsolve)
        │
        ▼
Objectives (11 scalar values)          ← 优化设计师维护
  → Pareto front CSV files             ← 调用计算员记录
        │
        ▼
Analysis pipeline:
  build_global_pareto.py   → 全局前沿 + ΔT_sp 中介分析
  analyze_conflict.py      → 冲突指标 (Spearman/C_ij/d_Euclidean)
  near_optimal_analysis.py → Part II: 近优空间参数分布
  off_design_eval.py       → Part III: 季节对鲁棒性评估
  plot_*.py                → 可视化 (pairwise / decomposition / evolution)
```

## 决策变量（9 维连续）

| 索引 | 变量 | 含义 | 典型范围 | 分组 |
|------|------|------|---------|------|
| x[0] | T_st_ht | 高温罐温度 [°C] | WP 依赖 (50–145) | 储能 |
| x[1] | dT_st_sp | 储热温差 [K] | WP 依赖 (15–80) | 储能 |
| x[2] | dT_hp_cs_gl | HP 冷源滑移 [K] | 0–20 | HP 侧 |
| x[3] | dT_hp_ev_sh | HP 蒸发过热度 [K] | 3–15 | HP 侧 |
| x[4] | dT_he_ev_sh | HE 蒸发过热度 [K] | 0.5–3 | ORC 侧 |
| x[5] | dT_hp_cd_sc | HP 冷凝过冷度 [K] | 0–15 | HP 侧 |
| x[6] | eta_max_cp | 压缩机等熵效率 [-] | 0.70–0.90 | 部件 |
| x[7] | eta_max_ex | 膨胀机等熵效率 [-] | 0.70–0.90 | 部件 |
| x[8] | eta_pm | 泵/马达机械效率 [-] | 0.45–0.55 | 部件 |

## CB 构型命名规则

`{HP 类型}{HP 循环}_[HP 后缀]_{ORC 类型}{ORC 循环}`

- **HP/ORC 类型**：`SB` = Subcritical Basic, `SR` = Subcritical Regenerative
- **HP 循环**：`VCH` = Vapor Compression Heat pump, 后缀 `P`
- **ORC 循环**：`ORC` = Organic Rankine Cycle
- **储能**：`STES2T` = Sensible Thermal Energy Storage 2-Tank

示例：`SRVCHP_SBORC_STES2T` = Recuperated HP + Basic ORC + 双罐感热储能

4 种构型：`SBVCHP_SBORC`, `SBVCHP_SRORC`, `SRVCHP_SBORC`, `SRVCHP_SRORC`

## 六工作点（DC-A 至 DC-F）

| WP | 冷却技术 | T_hs [°C] | T_cs [°C] | ΔT [K] | 季节 | Li 阈值关系 |
|----|---------|-----------|-----------|--------|------|-----------|
| DC-A | 风冷 | 35 | 5 | 30 | 冬 | 远低于 60°C |
| DC-B | 风冷 | 40 | 25 | 15 | 夏 | 低于 60°C |
| DC-C | 冷板液冷 | 50 | 5 | 45 | 冬 | 接近阈值 |
| DC-D | 冷板液冷 | 55 | 25 | 30 | 夏 | 接近阈值 |
| DC-E | 高性能液冷 | 65 | 5 | 60 | 冬 | 超过阈值 |
| DC-F | 高性能液冷 | 75 | 25 | 50 | 夏 | 远超阈值 |

**季节对**：DC-A/B（风冷）、DC-C/D（冷板液冷）、DC-E/F（高性能液冷）→ 为 Part III off-design 提供实验设计。

## 工质候选

**HP 工质**（T_crit > T_st_ht_max + 20K）：R1233zd(E) (166.5°C), R245fa (153.9°C), R600a (134.7°C), R600 (152.0°C)

**ORC 工质**（T_crit > T_cs + 20K）：R1234ze(E) (109.4°C), R227ea (101.8°C), R134a (101.1°C), R152a (113.3°C)

每个工况自动过滤热力学不可行工质对（`run_optimization.py: get_fluid_combos()`）。

## 11 个优化目标

### 热力学目标（9 个，无需额外参数）
| 名称 | 含义 | 方向 |
|------|------|------|
| `eta_p2p` | 往返效率 η_P2P = COP_HP × η_ORC | max |
| `energy_density_thermal` | 热能密度 e_th [kWh/m³] | max |
| `exergy_efficiency` | 㶲效率 η_ex | max |
| `energy_density_electric` | 电能量密度 [kWh_el/m³] | max |
| `cop_hp` | 热泵 COP | max |
| `eta_he` | 热机热效率 | max |
| `carnot_ratio` | η_P2P / η_Carnot | max |
| `storage_exergy_density` | 储能㶲密度 [kWh_ex/m³] | max |
| `neg_storage_volume` | 负储罐体积（最小化） | max |

### 经济目标（2 个，需 `economic_params`）
| 名称 | 含义 | 方向 |
|------|------|------|
| `neg_lcos` | 负平准化储能成本（最小化 LCOS） | max |
| `neg_specific_capex` | 负单位容量投资（最小化） | max |

## 常用命令

### 优化运行（从 `pure_deap_nsga/` 执行）
```bash
# 全批量（所有 WP × 构型 × 工质对）
python3 run_optimization.py --verbose

# 单工况
python3 run_optimization.py --wp DC-A --verbose

# 单构型
python3 run_optimization.py --cfg SBVCHP_SBORC --verbose

# 精确复现
python3 run_optimization.py --wp DC-C --cfg SRVCHP_SRORC --seed 123 --verbose
```

### 分析脚本
```bash
# 全局 Pareto 构建 + 降维判断
python3 build_global_pareto.py

# 冲突分析
python3 analyze_conflict.py --wp DC-A

# 近优分析 (Part II)
python3 near_optimal_analysis.py --wp DC-A
python3 near_optimal_analysis.py --wp DC-A --top-frac 0.10 --cv-low 0.10 --cv-high 0.20

# Off-design 评估 (Part III)
python3 off_design_eval.py                    # 全部 3 个季节对
python3 off_design_eval.py --pair DC-A_DC-B   # 单季节对
python3 off_design_eval.py --sweep dT_st_sp   # real-choice 参数扫描
```

### 可视化
```bash
# 成对 Pareto 散点图
python3 plot_pareto_pairwise.py "results/pareto_DC-A_SBVCHP_SBORC_R1233zd(E)_R1234ze(E).csv" \
    --config optimization_config.json --out-dir plots

# 按构型分解
python3 plot_config_decomposition.py

# 六工况演化图
python3 plot_six_wp_evolution.py
```

### 测试
```bash
cd pure_deap_nsga
python3 test_optimizer.py
```

## 论文三层架构（v3.0）

与 Laterre (2024/2025/2026) 三篇直接对话：

| 部分 | 内容 | 对应脚本 | Laterre 对话性质 |
|------|------|---------|---------------|
| Part I §3 | 六工况三元悖论冲突映射 | `build_global_pareto.py`, `analyze_conflict.py` | **延伸 + 分歧**（e_th 替代 ρ_el，证伪 η_ex 弱冲突） |
| Part II §4 | 全局前沿近优设计 | `near_optimal_analysis.py` | **延伸 + 扩展**（双端元近优分析，跨工况 must-have/real-choice 稳定性） |
| Part III §5 | 季节对 off-design 鲁棒性 | `off_design_eval.py` | **原创贡献**（完成 Laterre §3.4.2 未完成的 off-design 分析） |

### 五个核心创新点（C1–C5）
1. **C1**：六工况冲突强度演化谱（15K → 60K），ΔT 依赖型维度压缩判据
2. **C2**：e_th 替代 ρ_el 揭示 ORC 效率作为冲突中介的物理机制
3. **C3**：SRVCHP 在 ΔT < 60K 的热力学必要性——数据中心 HP 回热器不可省略
4. **C4**：must-have/real-choice 分类的跨工况一致性——等熵效率始终 must-have，dT_st_sp 始终 real-choice
5. **C5**：D_eff 是唯一跨季节鲁棒策略；冬→夏可行，夏→冬永远不可行

## 文献核心（11 篇，详见 `paper/文献锚定方案_M2.md`）

| ID | 文献 | 角色 | 关键论断 |
|----|------|------|---------|
| L1 | Laterre (2025) PhD | 三元悖论框架 | 非对称冲突 → 降维合理性 |
| L2 | Laterre et al. (2024) Energy | 30K ΔT 临界点 | ΔT < 30K: SR 优势→SB；ΔT = 30K: 设计转折 |
| L3 | Laterre et al. (2026) ECM | 近优设计方法 | must-have vs real-choice 区分 |
| L4 | Li et al. (2024) | 最优储热温度 | T_hs > 60°C 时 T_sto,hot 取最小值（η_P2P 视角） |
| L5 | Dumont & Lemort (2020) Energy | CB 性能映射奠基 | 废热回收 CB 的可行性 |
| L6 | Yuan et al. (2025) RSER | DC 废热综述 | 废热温度范围 25–80°C |
| L7 | ASHRAE TC 9.9 (2021) | 冷却标准 | 风冷/液冷温度分类 |
| L8 | Frate et al. (2019) ATE | HP 工质筛选 | 高温热泵工质适用性 |
| L9 | Deb et al. (2002) IEEE-TEC | NSGA-II 算法 | 多目标进化算法 |
| L10 | McTigue & Neises (2024) JES | Off-design 方法 | PTES 季节性性能评估 |
| L11 | Poletto et al. (2025) ATE | DC CB 技术经济 | 热售价格为 IRR 最大敏感性因素 |

## 注意事项

1. **`src/` 不可随意修改**：CBSim 热力学核心来自 Laterre (2025)，路径通过 `pathlib.Path(__file__).resolve()` 动态解析。仅在修复求解器收敛问题时才修改。
2. **DEAP 全局状态隔离**：`NSGAOptimizer._setup_deap()` 使用 `id(self)` 创建唯一 creator 名称（`f'FitnessMax_{id(self)}'`），避免批量运行时 DEAP 全局状态冲突。
3. **不可行解惩罚**：`INFEASIBLE_PENALTY = -1e6`，远小于任何可行目标值，确保不可行解被 NSGA-II 自动淘汰。所有目标函数返回此值时需保持符号一致性。
4. **工质筛选先于优化**：`get_fluid_combos()` 在优化前过滤热力学不可行工质对，避免无效计算。
5. **结果文件不纳入版本控制**：`results/` 和 `plots/` 目录内容通过 `.gitignore` 排除。
6. **`_archive/` 仅供参考**：不得导入或依赖归档脚本。如需恢复某个可视化技巧，复制代码到新脚本。
7. **论文 v2.0 路线已放弃**：不再使用 Lorenz 效率解耦框架和 CSWD 动态仿真。当前全部工作遵循 v3.0 路线。

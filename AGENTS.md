# AGENTS.md — CBSim 多 Agent 协作系统

本文档定义 CBSim 项目的 7 角色 Agent 协作体系。CLAUDE.md 包含完整的项目总览、目录树和命令参考。

## Agent 调用总则

每个 Agent 有严格的职责边界。调用时使用 Agent 工具，指定相应角色：

| Agent | subagent_type | 关键词触发 |
|-------|--------------|-----------|
| 构型设计师 | general-purpose | 构型、工质、工作点定义、边界约束、optimization_config |
| 建模工程师 | general-purpose | src/ 修改、CBSim 收敛、CoolProp、fsolve、构型类实现 |
| 优化设计师 | general-purpose | DEAP、NSGA、目标函数、Pareto、冲突指标、绘图脚本 |
| 文献阅读员 | general-purpose | 文献依据、论文大纲、引用、研究空白、Laterre/Li |
| 验收测试 | general-purpose | 运行测试、验证结果、检查输出、可复现性 |
| 调用计算员 | general-purpose | 执行优化、批量运行、记录结果、耗时统计 |
| Bug 反馈工程师 | general-purpose | 报错、traceback、收敛失败、INFEASIBLE_PENALTY |

## 角色定义

### 1. 构型设计师
**领域**：热力学循环构型（SB/SR × VCHP/ORC）、工质筛选（T_crit > T_max + 20K）、工作点边界约束
**不涉及**：数值建模、优化算法、文献
**输入**：文献阅读员提供的参数依据；用户的新构型需求
**输出**：`optimization_config.json` 中 `working_points`、`configurations`、`fluid_candidates` 部分
**详情**：见 memory `agent_config_designer.md`

### 2. 建模工程师
**领域**：`src/` 下 CBSim 核心（`_module_carnot_battery.py`、`_module_heat_pump.py`、`_module_heat_engine.py`）
**不涉及**：优化算法、分析脚本、文献
**输入**：构型设计师的新构型需求；Bug 反馈工程师的 CBSim 层错误诊断
**输出**：构型类实现、求解器收敛修复、API 文档更新
**详情**：见 memory `agent_modeling_engineer.md`

### 3. 优化设计师
**领域**：`deap_optimizer.py`、`run_optimization.py`、所有分析/绘图脚本、目标函数设计
**不涉及**：CBSim 核心修改、工质/构型选择、文献
**输入**：构型设计师的配置文件；建模工程师的 CBSim 接口；用户的新目标/分析需求
**输出**：优化结果、Pareto 前沿图表、近优分析、off-design 评估
**详情**：见 memory `agent_optimization_designer.md`

### 4. 文献阅读员
**领域**：11 篇核心文献、`文献锚定方案_M2.md`、`期刊论文初稿大纲（v3.0）.md`、文献参数配置表
**不涉及**：任何编程/建模/优化
**输入**：用户的研究问题；待获取文献清单
**输出**：文献依据链、论文大纲更新、研究空白定位
**详情**：见 memory `agent_literature_reader.md`

### 5. 验收测试
**领域**：`test_optimizer.py`（4 项测试）、结果文件完整性检查、可复现性验证
**不涉及**：修复 bug、修改代码、设计新测试
**输入**：调用计算员的执行结果；代码修改事件
**输出**：测试通过/失败报告
**详情**：见 memory `agent_acceptance_tester.md`

### 6. 调用计算员
**领域**：执行明确的 CLI 命令、记录日志和耗时
**不涉及**：修改代码、分析结果、诊断错误
**输入**：优化设计师或用户的执行方案
**输出**：输出文件路径、耗时、收敛统计
**详情**：见 memory `agent_computation_runner.md`

### 7. Bug 反馈工程师
**领域**：错误分类（A/B/C/D）、根因分析、诊断报告
**不涉及**：直接修改代码
**输入**：调用计算员的错误日志；验收测试的失败报告
**输出**：诊断报告 + 协同修复建议
**详情**：见 memory `agent_bug_feedback.md`

## 标准协作流程

### 流程 1：新增优化目标
```
用户要求新增目标
  → 构型设计师：确认是否需要新决策变量
  → 优化设计师：在 Objectives 类添加 @staticmethod + 注册 OBJECTIVE_MAP
  → 建模工程师：确认 CBSim 已输出所需中间变量
  → 调用计算员：运行单工况测试
  → 验收测试：验证目标函数返回值合理
  → (如有报错) Bug 反馈工程师 → 优化设计师/建模工程师协同排错
```

### 流程 2：新增 CB 构型
```
用户要求新增构型
  → 文献阅读员：提供文献依据
  → 构型设计师：定义构型名称和参数范围
  → 建模工程师：在 src/ 实现 {NewConfig}_STES2T 类
  → 优化设计师：在 optimization_config.json 注册
  → 调用计算员：运行单工况优化
  → 验收测试：验证 Pareto 前沿有效
  → (如有报错) Bug 反馈工程师 → 建模工程师协同排错
```

### 流程 3：修改论文大纲
```
用户要求修改论文结构
  → 文献阅读员：检查文献锚定是否仍然成立
  → 构型设计师：确认仿真设计决策是否受影响
  → 优化设计师：确认是否需要新的分析脚本
  → 文献阅读员：更新大纲 + 图表规划
```

### 流程 4：优化失败排查
```
调用计算员报告执行失败
  → Bug 反馈工程师：解析 traceback，分类 A/B/C/D
  → A 类（环境）：直接给出解决方案
  → B 类（CBSim）：移交建模工程师
  → C 类（优化层）：移交优化设计师
  → D 类（配置）：移交构型设计师
  → 调用计算员：重新执行验证修复
  → 验收测试：确认通过
```

## 文件所有权

| 文件/目录 | 主 Owner | 可修改 | 只读 |
|-----------|---------|--------|------|
| `src/_module_*.py` | 建模工程师 | 建模工程师 | 所有其他 Agent |
| `pure_deap_nsga/deap_optimizer.py` | 优化设计师 | 优化设计师 | 所有其他 Agent |
| `pure_deap_nsga/run_optimization.py` | 优化设计师 | 优化设计师 | 所有其他 Agent |
| `pure_deap_nsga/optimization_config.json` | 构型设计师 | 构型设计师、优化设计师 | 建模工程师、文献阅读员 |
| `pure_deap_nsga/analyze_*.py` | 优化设计师 | 优化设计师 | 所有其他 Agent |
| `pure_deap_nsga/plot_*.py` | 优化设计师 | 优化设计师 | 所有其他 Agent |
| `pure_deap_nsga/near_optimal_analysis.py` | 优化设计师 | 优化设计师 | 所有其他 Agent |
| `pure_deap_nsga/off_design_eval.py` | 优化设计师 | 优化设计师 | 所有其他 Agent |
| `pure_deap_nsga/test_optimizer.py` | 验收测试 | 验收测试、优化设计师 | 所有其他 Agent |
| `paper/文献锚定方案_M2.md` | 文献阅读员 | 文献阅读员 | 所有其他 Agent |
| `paper/期刊论文初稿大纲（v3.0）.md` | 文献阅读员 | 文献阅读员 | 所有其他 Agent |

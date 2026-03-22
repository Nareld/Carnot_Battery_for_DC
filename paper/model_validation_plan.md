# Laterre等(2024)模型验证详细方案

## 1. 验证案例选择

基于论文附录B，选择以下验证案例：

### 案例1：原始约束条件
- **位置**: t_hs = 50°C, t_cs = 30°C
- **约束条件**:
  - t_st,ht^max = 150°C
  - t_hp^max = 180°C (最大压缩机出口温度)
  - p_st = 7.5 bar (储热压力)
- **预期性能**: η_P2P = 39.7%

### 案例2：松弛约束条件
- **位置**: t_hs = 50°C, t_cs = 30°C
- **松弛约束**:
  - t_st,ht^max = 200°C
  - t_hp^max = 300°C
  - p_st = 20 bar
- **预期性能**: η_P2P = 43.0%

## 2. 验证参数设置

### 2.1 固定参数（基于论文表1）
| 参数 | 符号 | 值 | 单位 | 备注 |
|------|------|----|------|------|
| 热源温度 | t_hs | 50 | °C | 验证位置 |
| 热汇温度 | t_cs | 30 | °C | 验证位置 |
| 热汇温度滑移 | ΔT_cs,gl | 10 | K | 固定值[12] |
| ORC液体过冷度 | ΔT_orc,sc | 3 | K | 固定值[13] |
| 最小HP温升 | ΔT_hp^min | 5 | K | [19] |
| 最小ORC温降 | ΔT_orc^min | 5 | K | [19] |
| 压缩机效率 | η_is,comp | 0.75 | - | [19] |
| 膨胀机效率 | η_is,exp | 0.75 | - | [19] |
| 泵效率 | η_is,pmp | 0.50 | - | [19] |
| 最小过热度 | ΔT_sh^min | 3 | K | [13] |
| 最小HP过冷度 | ΔT_sc^min | 3 | K | [13] |
| 最小HP/ORC压力 | p_hp/orc^min | 0.5 | bar | [12] |
| 换热器夹点 | ΔT_pp | 3 | K | [12,19] |
| 压力损失 | Δp | 0.0 | bar | [12,13] |

### 2.2 设计变量（需要优化的值）
由于论文没有给出具体的设计变量值，我们需要：
1. **先运行单目标优化**找到最大化η_P2P的设计变量
2. **使用优化结果**进行验证计算

### 2.3 工质选择
论文中提到在这个位置(t_hs=50°C, t_cs=30°C)：
- 属于t_cs > 15°C区域
- 丙酮(acetone)在HP和ORC中占主导
- 建议使用丙酮作为初始工质选择

## 3. 验证流程

### 3.1 第一阶段：单目标优化寻找最优设计

**目标**: 找到最大化η_P2P的设计变量组合

**步骤**:
1. 设置优化问题：
   - 目标函数：最大化η_P2P
   - 设计变量：t_st,ht, ΔT_st,sp, ΔT_hs,gl, ΔT_hp,sc, ΔT_hp,sh, ΔT_orc,sh, fluid_hp, fluid_orc
   - 约束条件：表1中的所有约束

2. 运行单目标优化：
   - 算法：遗传算法或梯度优化
   - 种群大小：100
   - 最大评估次数：1000

3. 提取最优解：
   - 记录最优设计变量值
   - 记录最大η_P2P值

### 3.2 第二阶段：固定设计变量验证

**目标**: 使用最优设计变量进行验证计算

**步骤**:
1. 准备输入参数：
   - 使用第一阶段得到的最优设计变量
   - 设置固定参数（表1）
   - 配置模型选项

2. 运行模型计算：
   - 调用`main_cb.py`中的`eval_CB`函数
   - 计算η_P2P, η_II, ρ_el

3. 结果对比：
   - 对比计算值与论文值(39.7%/43.0%)
   - 计算相对误差

### 3.3 第三阶段：敏感性分析

**目标**: 验证关键参数的影响趋势

**步骤**:
1. 储热温度敏感性：
   - 固定其他变量，改变t_st,ht
   - 观察η_P2P变化趋势

2. 约束条件敏感性：
   - 对比原始约束和松弛约束
   - 验证性能提升趋势

## 4. 代码实现方案

### 4.1 文件结构
```
CBSim/
├── validation/
│   ├── __init__.py
│   ├── config.py          # 验证配置参数
│   ├── optimizer.py       # 单目标优化器
│   ├── validator.py       # 验证计算器
│   ├── analyzer.py        # 结果分析器
│   └── visualize.py       # 可视化工具
├── validation_cases/
│   ├── case_original.py   # 原始约束案例
│   └── case_relaxed.py    # 松弛约束案例
└── validation_results/
    ├── data/              # 结果数据
    └── plots/             # 可视化图表
```

### 4.2 核心代码模块

#### 4.2.1 单目标优化器 (`optimizer.py`)
```python
class SingleObjectiveOptimizer:
    """单目标优化器，用于寻找最大化η_P2P的设计变量"""

    def __init__(self, case_config):
        self.case_config = case_config
        self.best_solution = None
        self.best_fitness = -float('inf')

    def optimize(self):
        """执行单目标优化"""
        # 实现遗传算法或梯度优化
        # 调用现有优化框架

    def extract_design_variables(self):
        """提取最优设计变量"""
        return self.best_solution
```

#### 4.2.2 验证计算器 (`validator.py`)
```python
class ModelValidator:
    """模型验证计算器"""

    def __init__(self, design_vars, fixed_params):
        self.design_vars = design_vars
        self.fixed_params = fixed_params

    def run_validation(self):
        """运行验证计算"""
        # 准备输入参数
        inputs = self.prepare_inputs()

        # 调用卡诺电池模型
        from main_cb import eval_CB
        results = eval_CB(**inputs)

        return results

    def prepare_inputs(self):
        """准备模型输入参数"""
        # 将设计变量和固定参数转换为模型输入格式
        pass
```

#### 4.2.3 结果分析器 (`analyzer.py`)
```python
class ResultAnalyzer:
    """结果分析器"""

    def __init__(self, calculated_results, paper_results):
        self.calc = calculated_results
        self.paper = paper_results

    def calculate_error(self):
        """计算相对误差"""
        error_p2p = abs(self.calc['eta_P2P'] - self.paper['eta_P2P']) / self.paper['eta_P2P'] * 100
        return {
            'eta_P2P_error': error_p2p,
            'is_valid': error_p2p < 5.0  # 5%误差阈值
        }

    def generate_report(self):
        """生成验证报告"""
        pass
```

## 5. 验证标准

### 5.1 性能指标误差标准
- **通过标准**: 相对误差 < 5%
- **警告标准**: 5% ≤ 相对误差 < 10%
- **失败标准**: 相对误差 ≥ 10%

### 5.2 趋势一致性标准
- 储热温度对η_P2P的影响趋势应与论文一致
- 约束松弛应导致性能提升
- 工质选择应符合论文观察模式

## 6. 实施步骤

### 步骤1：环境准备（第1天）
1. 检查Python环境 (3.8+)
2. 安装依赖包 (CoolProp, numpy, pandas, matplotlib)
3. 测试现有代码 (`main_cb.py`能否正常运行)

### 步骤2：单目标优化（第2天）
1. 实现单目标优化器
2. 运行优化寻找最优设计变量
3. 保存优化结果

### 步骤3：验证计算（第3天）
1. 使用最优设计变量运行模型
2. 计算性能指标
3. 对比论文结果

### 步骤4：敏感性分析（第4天）
1. 分析关键参数敏感性
2. 验证趋势一致性
3. 生成验证报告

## 7. 预期挑战与应对

### 挑战1：模型参数不一致
- **可能问题**: 本地模型参数与论文不完全一致
- **应对**: 仔细对比模型假设，逐步调整参数

### 挑战2：优化收敛问题
- **可能问题**: 单目标优化不收敛或陷入局部最优
- **应对**: 尝试不同优化算法，增加种群大小

### 挑战3：工质数据差异
- **可能问题**: CoolProp版本不同导致工质性质差异
- **应对**: 记录CoolProp版本，必要时固定版本

## 8. 交付成果

### 8.1 代码成果
- 完整的验证代码框架
- 可复用的验证工具

### 8.2 数据成果
- 最优设计变量值
- 验证计算结果
- 误差分析数据

### 8.3 文档成果
- 验证技术报告
- 代码使用说明
- 问题排查指南

## 9. 下一步行动

### 立即行动：
1. 测试现有`main_cb.py`代码能否正常运行
2. 准备验证代码框架
3. 开始实现单目标优化器

### 关键检查点：
- [ ] `main_cb.py`可以正常导入和运行
- [ ] CoolProp安装正确，能查询工质性质
- [ ] 可以成功调用`eval_CB`函数
- [ ] 单目标优化器能正常运行

---
*方案制定时间: 2025-12-01*
*基于: Laterre等(2024)论文和现有CBSim代码库*
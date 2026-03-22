# CBSim 开发环境配置指南

## 环境要求

- Python 3.11（推荐）
- uv 包管理器（跨平台，替代 conda）

## 快速开始

### 1. 安装 uv

```bash
# macOS (Homebrew)
brew install uv

# Linux / macOS (curl)
curl -LsSf https://astral.sh/uv/install.sh | sh

# Windows (PowerShell)
powershell -c "irm https://astral.sh/uv/install.ps1 | iex"
```

### 2. 创建虚拟环境

```bash
cd CBSim_clean
uv venv .venv --python 3.11
```

### 3. 安装依赖

```bash
# 安装核心依赖
uv pip install --python .venv/bin/python numpy scipy pandas matplotlib seaborn tqdm h5py CoolProp deap pyDOE sobolsequence pvlib

# 安装 RHEIA（本地可编辑模式）
uv pip install --python .venv/bin/python -e opt/RHEIA/ --no-deps
```

### 4. 激活环境

```bash
# macOS / Linux
source .venv/bin/activate

# Windows
.venv\Scripts\activate
```

### 5. 验证安装

```bash
python test_cbsim.py
```

预期输出：
```
=== CBSim Single Point Test PASSED ===
eta_P2P [%]:  19.9774
eta_II  [%]:  19.9774
E_dens_th [kWh/m3]: 33.7607
E_dens_el [kWh/m3]: 2.8348
Time: ~0.6s
```

## 重要说明

### scipy 版本约束

CBSim 的热力学求解器（`_module_heat_pump.py`）使用 `scipy.optimize.fsolve` 和 `least_squares`，
这些函数调用了 CoolProp 的 `AbstractState.update()` 方法。

**scipy >= 1.12 引入了对标量数组处理方式的变更**，导致与 CoolProp 7.x 的 AbstractState API 不兼容，
会产生 `TypeError: only 0-dimensional arrays can be converted to Python scalars` 错误。

因此，**必须使用 scipy 1.11.x**：

```bash
uv pip install --python .venv/bin/python "scipy==1.11.4"
```

### 跨平台路径

所有硬编码的绝对路径（原始 `/home/oxford/CBSim_clean/`）已替换为基于 `pathlib.Path(__file__).resolve()` 
的动态路径计算，支持 macOS、Linux 和 Windows。

## 目录结构

```
CBSim_clean/
├── .venv/                    # uv 虚拟环境（不提交到 git）
├── pyproject.toml            # 项目依赖配置
├── README.md                 # 原始项目说明
├── README_ENV.md             # 本文件：环境配置指南
├── main_cb.py                # 卡诺电池主脚本
├── main_hp.py                # 热泵主脚本
├── main_he.py                # 热机主脚本
├── test_cbsim.py             # 环境验证测试
├── src/                      # 核心热力学模型
│   ├── _module_carnot_battery.py
│   ├── _module_heat_pump.py
│   ├── _module_heat_engine.py
│   └── _module_plots.py
├── opt/                      # 优化框架
│   ├── RHEIA/                # RHEIA 优化框架（本地安装）
│   └── multi_objective_optimization_reproduce/  # 多目标优化脚本
├── simulation_notes/         # 模拟思路文档（新增）
└── paper/                    # 参考文献和分析文档
```

## 从 conda 迁移

原始开发环境使用 conda 管理，迁移到 uv 的主要变化：

| conda | uv |
|-------|-----|
| `conda create -n cbsim python=3.11` | `uv venv .venv --python 3.11` |
| `conda activate cbsim` | `source .venv/bin/activate` |
| `conda install package` | `uv pip install package` |
| `conda env export > env.yml` | `uv pip freeze > requirements.txt` |

uv 的优势：
- 速度更快（Rust 实现）
- 无需 conda 基础安装
- 与标准 pip 完全兼容
- 更好的跨平台支持

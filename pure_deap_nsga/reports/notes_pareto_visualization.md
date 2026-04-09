# 帕累托前沿可视化与分析技术笔记

> 工况：DC-A / SBVCHP\_SBORC / R245fa–R134a  
> 优化算法：DEAP NSGA-II（三目标，100 个帕累托解）  
> 日期：2026-04-02

---

## 1. 优化目标定义

| 符号 | 含义 | 单位 | 优化方向 |
|------|------|------|----------|
| $\eta_{p2p}$ | 往返效率（Round-trip efficiency） | — | 最大化 |
| $e_{th}$ | 热储能密度（Thermal energy density） | kWh m⁻³ | 最大化 |
| $\eta_{ex}$ | 㶲效率（Exergy efficiency） | — | 最大化 |

三个目标均为"越大越好"，NSGA-II 内部取负值处理为最小化问题。

---

## 2. 可视化方法选择

### 2.1 两两帕累托前沿散点图（已实现）

对 $n$ 个目标，绘制所有 $\binom{n}{2}$ 对的二维投影，是最直接的多目标前沿展示方式。

**实现要点：**

- **颜色编码**：用 $\eta_{p2p}$ 的归一化值统一着色（plasma colormap），使同一解在不同子图中可视觉追踪
- **连接线**：将点按横轴排序后依次连线，突出前沿走势；线条设为浅灰色，避免喧宾夺主
- **轴格式**：效率类目标自动切换为百分比刻度，密度类保留物理量纲
- **信息面板**：顶部统一展示工况元数据（T\_source、T\_sink、制冷剂对等），便于批量比较时快速识别

**适用场景：** 目标数 $\leq 4$，重点关注两两间的权衡关系。

### 2.2 方法局限性

| 问题 | 原因 |
|------|------|
| 解集在某些 2D 投影中弥散 | 三维前沿面投影到二维时，第三维信息丢失 |
| 颜色仅能编码一个额外维度 | 无法同时呈现所有目标之间的联合关系 |
| 图数量随目标数二次增长 | 目标数 $\geq 5$ 时子图过多，不易阅读 |

---

## 3. 帕累托前沿结果分析

### 3.1 目标间权衡关系

**① $e_{th}$ vs $\eta_{p2p}$（左图）— 强权衡**

呈现清晰的下凸型帕累托曲线。$e_{th}$ 高区（$\sim$34 kWh m⁻³）对应极低 $\eta_{p2p}$（$\sim$1%），高效率区（$\eta_{p2p} > 35\%$）的 $e_{th}$ 急剧下降至 $\sim$9 kWh m⁻³。

物理机制：高储热密度要求高 $T_{st,ht}$ 和大温差 $\Delta T_{st}$，这会增大热泵压比、降低 COP，同时 ORC 的膨胀器进口条件恶化，最终拉低往返效率。

**② $\eta_{ex}$ vs $\eta_{p2p}$（中图）— 强正相关**

两者近似线性正相关（前沿基本为单调递增），说明㶲效率和往返效率共享相似的物理驱动因素（夹点温差损失、组件等熵效率）。两者不构成真正意义上的"权衡"，更多是同一热力学完善度的不同表达。

**③ $\eta_{ex}$ vs $e_{th}$（右图）— 弱耦合，显著弥散**

解集明显散开，无清晰前沿曲线。这是本工况最值得关注的特征，原因详见第 4 节。

### 3.2 设计空间特征

- $\eta_{p2p}$ 范围：1.0%–46.9%，跨度大，说明参数空间存在显著的性能梯度
- $e_{th}$ 范围：8.6–34.3 kWh m⁻³，上限受 $T_{st,ht,max}$ = 120 °C 约束
- $\eta_{ex}$ 范围：0.1%–30.9%，低值端对应储热优先解，高值端对应热力学精细化解

---

## 4. 帕累托前沿弥散成因分析

### 4.1 高维投影效应（根本原因）

NSGA-II 在**三维目标空间**中维护非支配解集，这些解构成一张连续的前沿**曲面**。投影到任意二维平面时，原本在第三维分离的解会叠加到同一平面坐标，表现为弥散。

$$
\text{3D 前沿面} \xrightarrow{\text{投影}} \text{2D 散点（含遮蔽信息）}
$$

$\eta_{ex}$ vs $e_{th}$ 投影弥散最严重，因为这两个目标的"公共驱动参数"最少，$\eta_{p2p}$ 作为隐藏第三维在其间产生大量中间状态解。

### 4.2 目标间物理耦合度差异

| 目标对 | 共同主控参数 | 耦合强度 |
|--------|-------------|---------|
| $\eta_{p2p}$ – $e_{th}$ | $T_{st,ht}$、$\Delta T_{st}$ | 强（负相关） |
| $\eta_{p2p}$ – $\eta_{ex}$ | 夹点温差、等熵效率 | 强（正相关） |
| $\eta_{ex}$ – $e_{th}$ | 各自独立的控制路径 | 弱 |

### 4.3 多峰设计路径共存

设计空间中存在两条性能路径，均能产生非支配解：

- **路径 A**（储热优先）：高 $T_{st,ht}$ → 高 $e_{th}$，但循环夹点损失大 → 低 $\eta_{ex}$
- **路径 B**（效率优先）：低 $T_{st,ht}$ + 精细夹点控制 → 低 $e_{th}$，但 $\eta_{ex}$ 高

两条路径在 $\eta_{ex}$–$e_{th}$ 平面上形成不连续簇，呈现弥散形态。

### 4.4 NSGA-II 拥挤距离机制

算法通过拥挤距离在前沿上均匀保留解，刻意维持多样性。这在高维空间中是正确行为，但在任意 2D 投影中会呈现弥散，并非算法收敛不足的体现。

---

## 5. 改进可视化方案

### 方案 A：3D 散点图

直接在三维目标空间中展示前沿面，消除投影信息损失。

```python
fig = plt.figure()
ax  = fig.add_subplot(111, projection='3d')
sc  = ax.scatter(df['eta_p2p'], df['energy_density_thermal'], df['exergy_efficiency'],
                 c=df['eta_p2p'], cmap='plasma', s=30)
ax.set_xlabel(r'$\eta_{p2p}$'); ax.set_ylabel(r'$e_{th}$'); ax.set_zlabel(r'$\eta_{ex}$')
```

**优点**：无投影失真，直观呈现前沿曲面形态  
**缺点**：静态图存在遮挡，需交互旋转（推荐 `plotly`）

---

### 方案 B：平行坐标图（Parallel Coordinates）

每个解绘制为一条折线，纵轴为各目标值，横轴为目标序列。

```python
import plotly.express as px
fig = px.parallel_coordinates(
    df, dimensions=['eta_p2p', 'energy_density_thermal', 'exergy_efficiency'],
    color='eta_p2p', color_continuous_scale='Plasma',
    labels={...}
)
fig.show()
```

**优点**：目标数量不受限，可同时展示 $n \geq 4$ 个目标；交叉线密集区域揭示目标间相关性  
**缺点**：解数量多时视觉拥挤，需配合交互筛选

---

### 方案 C：散点矩阵 + 核密度叠加（Scatter Matrix）

将所有两两投影组合在一个矩阵中，对角线绘制边际分布（KDE 或直方图），非对角线绘制散点。

```python
import seaborn as sns
g = sns.PairGrid(df[obj_cols], diag_sharey=False)
g.map_upper(sns.scatterplot, hue=df['eta_p2p'], palette='plasma', s=20, alpha=0.7)
g.map_lower(sns.kdeplot, fill=True, alpha=0.4)
g.map_diag(sns.kdeplot, fill=True)
```

**优点**：同时呈现两两关系和各目标的边际分布，密度信息揭示解集聚集规律  
**缺点**：对角线和上/下三角重复，在目标数多时图幅较大

---

### 方案 D：目标相关性热力图

定量展示目标间的 Pearson / Spearman 相关系数，作为散点图的补充分析。

```python
corr = df[obj_cols].corr(method='spearman')
sns.heatmap(corr, annot=True, fmt='.2f', cmap='RdBu_r',
            vmin=-1, vmax=1, square=True, linewidths=0.5)
```

**优点**：一张图量化所有目标对的耦合强度，是弥散成因分析的直接证据  
**缺点**：仅反映线性/单调相关，无法呈现非线性权衡形态

---

### 方案 E：雷达图 + 典型解标注

从帕累托前沿中选取若干**典型极端解**（各目标最优解、折中解），以雷达图对比各解的目标全貌。

```python
# 典型解：各目标最大值处的解 + 几何中心解
extreme_solutions = {
    'Max η_p2p':  df.loc[df['eta_p2p'].idxmax()],
    'Max e_th':   df.loc[df['energy_density_thermal'].idxmax()],
    'Max η_ex':   df.loc[df['exergy_efficiency'].idxmax()],
    'Balanced':   df.loc[((df[obj_cols] - df[obj_cols].mean()).abs().sum(axis=1)).idxmin()],
}
```

**优点**：辅助决策，将抽象前沿转化为可解释的具体设计方案  
**缺点**：需人工或规则选取"典型解"，有一定主观性

---

## 6. 方案选用建议

| 场景 | 推荐方案 |
|------|----------|
| 目标数 = 3，需投稿图表 | **3D 散点图**（静态旋转角度） + 当前两两投影 |
| 目标数 ≥ 4 | **平行坐标图**（plotly 交互）|
| 深入分析耦合机制 | **相关性热力图** + **散点矩阵** |
| 辅助工程决策选解 | **雷达图**（典型解对比）|
| 跨工况横向比较 | 将所有构型前沿叠加在同一 2D 散点图，用颜色区分构型 |

---

*脚本位置：`pure_deap_nsga/plot_pareto_pairwise.py`*  
*结果位置：`pure_deap_nsga/plots/`*

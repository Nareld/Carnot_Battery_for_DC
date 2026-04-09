# DC-A 工况三目标冲突机理分析报告

> 工况：DC-A — $T_{hs}$ = 35°C，$T_{cs}$ = 5°C，$\Delta T_{hs-cs}$ = 30 K  
> 分析范围：42 种构型/制冷剂组合  
> 参考：Laterre (2025) §3.3.1–3.3.3  
> 日期：2026-04-08  
> 状态：**初步机理推断**，待热力学参数实测数据验证

---

## 1. 分析框架

本报告将量化冲突指标与设计变量极端点分析相结合，对三目标冲突的物理来源作出推断。核心思路：**若两个目标在最优解处需要的设计变量方向相反，则产生冲突；若方向相近，则协同或弱冲突。**

关键设计变量及其对三目标的定性影响：

| 设计变量 | $\eta_{p2p}$ 最优方向 | $e_{th}$ 最优方向 | $\eta_{ex}$ 最优方向 |
|---------|:-------------------:|:----------------:|:-----------------:|
| $T_{st,ht}$ [°C] | 中等（临界点行为）| 最大化 | 较高 |
| $\Delta T_{st,sp}$ [K] | **最小化**（~15K）| **最大化**（~60K）| **最小化**（~15–19K）|
| $\Delta T_{hs,gl}$ [K] | 最小化 | 较大 | 中等（50–65%）|

---

## 2. 三目标冲突的设计变量根源

### 2.1 $\Delta T_{st,sp}$ 是冲突的核心驱动轴

各目标最优解处的 $T_{st,ht}$ 和 $\Delta T_{st,sp}$（跨 42 种构型的平均值）：

| 目标极值 | SBVCHP\_SBORC | SBVCHP\_SRORC | SRVCHP\_SBORC | SRVCHP\_SRORC |
|---------|:-------------:|:-------------:|:-------------:|:-------------:|
| max $\eta_{p2p}$: $(T_{st,ht},\ \Delta T_{sp})$ | 70.4°C / **15.1K** | 82.2°C / **15.1K** | 75.5°C / **16.5K** | 85.2°C / **16.8K** |
| max $e_{th}$: $(T_{st,ht},\ \Delta T_{sp})$ | 81.9°C / **60.0K** | 103.5°C / **56.2K** | 81.8°C / **60.0K** | 103.8°C / **57.2K** |
| max $\eta_{ex}$: $(T_{st,ht},\ \Delta T_{sp})$ | 82.9°C / **15.5K** | 90.5°C / **15.6K** | 91.1°C / **19.4K** | 97.5°C / **19.2K** |

**$\Delta T_{sp}$ 缺口（各目标最优 $\Delta T_{sp}$ 之差）：**

| 目标对 | SBVCHP\_SBORC | SBVCHP\_SRORC | SRVCHP\_SBORC | SRVCHP\_SRORC |
|--------|:---:|:---:|:---:|:---:|
| $e_{th}$ max – $\eta_{p2p}$ max | **+44.9K** | **+41.0K** | **+43.5K** | **+40.4K** |
| $\eta_{ex}$ max – $\eta_{p2p}$ max | **+0.4K** | **+0.5K** | **+2.9K** | **+2.5K** |
| $e_{th}$ max – $\eta_{ex}$ max | **+44.5K** | **+40.5K** | **+40.6K** | **+37.9K** |

**推断 1**：$\eta_{p2p}$–$e_{th}$ 的极端冲突（$C_{ij}$ = 0.979）源于两者对 $\Delta T_{sp}$ 需求的**根本对立**：最大化 $e_{th}$ 需要 $\Delta T_{sp} \approx 60$K，最大化 $\eta_{p2p}$ 需要 $\Delta T_{sp} \approx 15$K，差距约 40–45K，且**与 CB 构型和制冷剂完全无关**。这是 DC-A 工况下三难困境的**结构性矛盾**，不可通过构型选择消除。

**推断 2**：$e_{th}$–$\eta_{ex}$ 冲突（$C_{ij}$ = 0.873）与 $\eta_{p2p}$–$e_{th}$ 同源：$\eta_{ex}$ 最优解同样需要小 $\Delta T_{sp}$（15–19K），与 $e_{th}$ 的最优方向相反。差距与 $\eta_{p2p}$–$e_{th}$ 相近（约 38–45K），但 $\eta_{ex}$ 对应的 $T_{st,ht}$ 更高（比 $\eta_{p2p}$ 高约 10–15°C），使两者目标函数值的实际损失稍小于 $\eta_{p2p}$–$e_{th}$，因此冲突强度略低。

### 2.2 与 Laterre §3.3.1 的对照

Laterre 对 $\Delta T_{sp}$ 的解释：

> *"A large spread makes it possible to lower the condensation temperature in the HP... while at the same time allowing significant subcooling, thus improving COP_HP. However, as this also penalises η_ORC, there is an optimal spread to be found."*

DC-A 结果与 Laterre 一致：$\eta_{p2p}$ 最优的 $\Delta T_{sp}$ = 15–17K，显著低于密度最优的 60K。这与 Laterre 在 $T_{\rm cs} = 15°{\rm C}$ 附近区域的设计指南（$\Delta T_{sp}$ 取中等值以平衡 COP$_{\rm HP}$ 与 $\eta_{\rm ORC}$）高度一致。

---

## 3. ORC 构型对冲突结构的影响机制

### 3.1 ORC 回热器（SBORC → SRORC）是 $\eta_{p2p}$–$\eta_{ex}$ 关系反转的主因

| 指标 | SBORC | SRORC | 变化方向 |
|------|:-----:|:-----:|---------|
| $r_s(\eta_{p2p}$–$\eta_{ex})$ | +0.536 | −0.269 | 从协同翻转为冲突 |
| $C_{ij}(\eta_{p2p}$–$\eta_{ex})$ | 0.402 | 0.535 | 冲突增强 |
| $T_{st,ht}$ 缺口（$\eta_{ex}$max − $\eta_{p2p}$max） | ~12°C | ~8°C（SBVCHP） | 缺口略缩小 |
| $e_{th}$ max 均值 | 34.3 kWh/m³ | 31.8–32.4 kWh/m³ | **降低 5–7%** |

**机制推断（SRORC 如何改变 $\eta_{p2p}$–$\eta_{ex}$ 关系）：**

1. **约束冷罐温度下限**：ORC 回热器要求膨胀机出口温度高于冷罐温度加夹点，这限制了 $\Delta T_{sp}$ 的可用上限（Laterre §4.3.1 明确指出这是 SRORC 不能最大化 $\rho_{el}$ 的原因），导致 SRORC 的 $e_{th}$ max 比 SBORC 降低约 2.2 kWh/m³。

2. **解耦 $\eta_{ex}$ 的提升路径**：在 SBORC 中，$\eta_{ex}$ 的改善主要依赖与 $\eta_{p2p}$ 相同的参数路径（适中 $T_{st,ht}$、小 $\Delta T_{sp}$），因此两者正相关。在 SRORC 中，回热器提供了一条**替代路径**——通过回收膨胀机出口显热来提升 $\eta_{ex}$，这条路径对应不同的最优 $T_{st,ht}$（高约 8°C）。两条路径并存使 Pareto 前沿在 $\eta_{p2p}$–$\eta_{ex}$ 平面上变得弥散，相关性降低。

3. **进一步：双回热（SRVCHP\_SRORC）使关系转负**：当 HP 和 ORC 都引入回热器时，每个目标都有独立的"偏好构型状态"，$\eta_{p2p}$ 的最优解（中等 $T_{st,ht}$，小 $\Delta T_{sp}$）与 $\eta_{ex}$ 的最优解（更高 $T_{st,ht}$ 约 97.5°C，略大 $\Delta T_{sp}$）出现明显分离，Pareto 前沿需要在两个方向之间trade-off → 负相关（$r_s$ = −0.499）。

**待验证**：需确认 SRORC 条件下，高 $\eta_{ex}$ 解与低 $\eta_{ex}$ 解在回热器传热量、膨胀机出口温度上的差异，以证实回热器是否确实提供了额外的 $\eta_{ex}$ 改善路径。

---

## 4. HP 构型对冲突结构的影响机制

### 4.1 HP 回热器（SBVCHP → SRVCHP）的影响

| 指标 | SBVCHP | SRVCHP | 变化方向 |
|------|:------:|:------:|---------|
| $\eta_{p2p}$ max（SBORC） | 0.467 | 0.513 | **+9.9%**（显著提升）|
| $\eta_{ex}$ max（SBORC） | 0.294 | 0.315 | **+7.1%** |
| $T_{st,ht}$ at $\eta_{p2p}$ max | 70.4°C（SBORC） | 75.5°C（SBORC） | **+5.1°C**（上移）|
| $r_s(\eta_{p2p}$–$\eta_{ex})$（SBORC） | +0.627 | +0.445 | 协同减弱 |
| $C_{ij}(\eta_{p2p}$–$\eta_{ex})$ | 0.365 | 0.440 | 冲突轻微增强 |

**机制推断（HP 回热器为何提升绝对性能但轻微增加 $\eta_{p2p}$–$\eta_{ex}$ 冲突）：**

1. **提升 $\eta_{p2p}$ 的机制**：HP 回热器在压缩机入口端利用膨胀阀前液态制冷剂的过冷热量预热气态制冷剂，实现更大的过冷度，直接提高 COP$_{\rm HP}$。这与 Laterre §3.3.2 的描述一致："subcooling in the HP... can in fact be as low as 5.5K... this is made possible by the presence of the recuperator"。

2. **最优 $T_{st,ht}$ 上移的机制**：HP 回热器将部分过冷㶲转移回循环，使相同 $T_{st,ht}$ 下 HP 的等效温升更高，系统可以承受更高的 $T_{st,ht}$ 而不超过压缩机排气温度限制。因此最优 $T_{st,ht}$ 上移约 5°C。

3. **$\eta_{p2p}$–$\eta_{ex}$ 协同减弱的机制**：$T_{st,ht}$ 上移使 $\eta_{p2p}$ 最优解向更高温度区间移动，而 $\eta_{ex}$ 的最优 $T_{st,ht}$ 也随之上移，但幅度更大（SBORC+SRVCHP：$\eta_{ex}$最优 $T_{st,ht}$ = 91.1°C，与 $\eta_{p2p}$ 最优的 75.5°C 相差 15.6°C；SBORC+SBVCHP：差距约 12.5°C）。温度缺口扩大使前沿在 $\eta_{p2p}$–$\eta_{ex}$ 平面上"展宽"，协同程度减弱。

**待验证**：需确认有无 HP 回热器时，相同流量下 HP 过冷度的变化量，以及 COP$_{\rm HP}$ 的增益分配（过冷效应 vs 回热提高进口干度的反效果）。

---

## 5. DC-A 处于 Laterre 临界点（$\Delta T_{hs-cs}$ = 30 K）的特殊性

### 5.1 临界点行为的体现

Laterre §3.3.1 的核心结论：

> *"For $\Delta T_{hs-cs} < 30$ K: $T_{TES}^{ht}$ is maximised [for max $\eta_{P2P}$]; for $\Delta T_{hs-cs} \geq 30$ K: $T_{TES}^{ht}$ is minimised [for max $\eta_{P2P}$]."*

DC-A ($\Delta T_{hs-cs}$ = 30K) 处于转变边界。观察到的 $T_{st,ht}$ at $\eta_{p2p}$ max：

- SBVCHP\_SBORC：70.4°C —— 既不是最大值（120°C），也不接近最小值（~50°C）
- SRVCHP\_SBORC：75.5°C —— 同样处于中间范围
- SBVCHP\_SRORC：82.2°C —— 回热器约束推高了最优温度
- SRVCHP\_SRORC：85.2°C —— 双回热进一步推高

这与 Laterre 的"过渡区"行为一致：$T_{st,ht}$ 不再由热力学的"全局最优"单一决定，而是在升温减小 HP lift（降低 COP$_{\rm HP}$）与升温提高 $\eta_{ORC}$ 之间寻找局部最优。

### 5.2 为何 DC-A 工况下 $\eta_{p2p}$ 没有"退化"为 TES+ORC

Laterre 指出，在高 $\Delta T_{hs-cs}$ 下，最大化 $\eta_{P2P}$ 导致 HP lift 趋于零，系统退化为 TES+ORC。DC-A 的 $\Delta T_{hs-cs}$ = 30K 处于临界点，HP lift 尚未完全消失：

- SBVCHP\_SBORC 下，$\eta_{p2p}$ max 对应 $T_{st,ht}$ = 70.4°C，远高于 $T_{hs}$ = 35°C
- 实际热泵温升（lift）约为 70 − 35 = **35°C**，仍有实质性的压缩升温作用

因此，DC-A 工况下 $\eta_{p2p}$ 仍是一个**有意义的优化目标**，不存在退化风险。这与 Part I 分析中预测的"DC-A 困境较弱"结论吻合。

---

## 6. 制冷剂选择的影响

### 6.1 HP 制冷剂（R1233zd(E) / R245fa / R600）的影响

| 制冷剂 | $r_s(\eta_{p2p}$–$e_{th})$ | $C_{ij}(\eta_{p2p}$–$e_{th})$ | $r_s(\eta_{p2p}$–$\eta_{ex})$ | $C_{ij}(\eta_{p2p}$–$\eta_{ex})$ |
|--------|:--:|:--:|:--:|:--:|
| R1233zd(E) | $-0.916 \pm 0.077$ | $0.987 \pm 0.026$ | $+0.147 \pm 0.496$ | $0.459 \pm 0.115$ |
| R245fa | $-0.925 \pm 0.104$ | $0.977 \pm 0.036$ | $+0.189 \pm 0.441$ | $0.463 \pm 0.127$ |
| R600 | $-0.928 \pm 0.084$ | $0.974 \pm 0.059$ | $+0.237 \pm 0.507$ | $0.456 \pm 0.155$ |

三种 HP 制冷剂之间的冲突指标差异**极小**（均在标准差范围内），构型类型对冲突结构的影响远大于 HP 制冷剂的影响。

**推断**：HP 制冷剂主要影响 COP$_{\rm HP}$ 的绝对值（临界温度与 $T_{cs}$、$T_{hs}$ 的匹配），但不改变热储能子系统（$T_{st,ht}$、$\Delta T_{sp}$）的最优配置方向，因此对冲突结构无显著影响。

### 6.2 ORC 制冷剂的影响

| 制冷剂 | $r_s(e_{th}$–$\eta_{ex})$ | $C_{ij}(e_{th}$–$\eta_{ex})$ | $e_{th}$ max (kWh/m³) | $\Delta T_{sp}$ at $e_{th}$ max |
|--------|:--:|:--:|:--:|:--:|
| R1234ze(E) | $-0.315 \pm 0.420$ | $0.854 \pm 0.155$ | 较大 | 60K |
| R134a | $-0.361 \pm 0.360$ | $0.825 \pm 0.200$ | **较小** | **55K** |
| R152a | $-0.674 \pm 0.083$ | $0.979 \pm 0.031$ | 较大 | 60K |
| R227ea | $-0.378 \pm 0.270$ | $0.887 \pm 0.104$ | 较大 | 60K |

R152a 作为 ORC 制冷剂时 $e_{th}$–$\eta_{ex}$ 冲突最强（$r_s = -0.674$，std 也最小），且仅出现在 SBORC 构型中（R152a 只有 SBVCHP\_SBORC 和 SRVCHP\_SBORC 两种）。R134a 对应最小的 $e_{th}$ max，可能是因为其临界温度（101.1°C）与 $T_{st,ht}$ 范围的匹配较差，限制了大 $\Delta T_{sp}$ 下的 ORC 蒸发压力。

**推断**：ORC 制冷剂主要通过改变 ORC 循环在大 $\Delta T_{sp}$ 下的热效率，间接影响 $e_{th}$–$\eta_{ex}$ 冲突强度。当 ORC 制冷剂在高蒸发温度下效率更高时（如 R152a），ORC 性能对 $\Delta T_{sp}$ 的敏感度更高，$e_{th}$–$\eta_{ex}$ 冲突更强。

---

## 7. 综合冲突机制拓扑图

```
          $T_{st,ht}$ & $\Delta T_{sp}$ 最优方向冲突
              ↓              ↓              ↓
      ┌───────────────────────────────────────────────┐
      │  $\eta_{p2p}$ max: 低 T_ht / 小 ΔT_sp (~15K) │
      │  $e_{th}$  max: 高 T_ht / 大 ΔT_sp (~60K)   │  ← 结构性矛盾
      │  $\eta_{ex}$ max: 高 T_ht / 小 ΔT_sp (~17K) │
      └───────────────────────────────────────────────┘
                           ↓
         冲突格局（ORC 构型是主要调节变量）：

         SBORC（无回热）：
           η_p2p 和 η_ex 共享小 ΔT_sp → 协同（r_s = +0.54）
           e_th 与两者均大 ΔT_sp 冲突 → 强冲突

         SRORC（有回热）：
           ORC 回热提供第二条 η_ex 改善路径（无需小 ΔT_sp）
           → η_p2p–η_ex 解耦 → 中性/弱冲突（r_s ≈ -0.27）
           但 e_th max 因冷罐温度约束下降约 5-7%

         SRVCHP_SRORC（双回热）：
           两条独立优化路径分离最大化 → 翻转为负（r_s = -0.50）
           三难困境最"软化"（e_th–η_ex C_ij = 0.70）
           但 e_th max 进一步受限
```

---

## 8. 待验证的关键推断

以下推断需结合实际帕累托解的热力学参数（循环状态点）进行验证：

| 编号 | 推断内容 | 验证方法 |
|------|---------|---------|
| H1 | SBORC 下 $\eta_{p2p}$ 与 $\eta_{ex}$ 同向变化，均受 $\Delta T_{sp}$ 控制 | 对比高/低 $\eta_{p2p}$ 解的 $\Delta T_{sp}$ 分布 |
| H2 | SRORC 的 $\eta_{ex}$ 高值解中，回热器传热量（$Q_{rec}$）显著大于 $\eta_{p2p}$ 高值解 | 提取并对比两组解的回热器热流 |
| H3 | SRVCHP 回热器通过提高过冷度（$\Delta T_{HP,sc}$）而非降低冷凝温度提升 COP | 对比有无 HP 回热器时的 $\Delta T_{HP,sc}$ 和冷凝温度 |
| H4 | DC-A 处于临界点的证据：$\eta_{p2p}$ 最优解的 HP lift 仍为正值（$T_{st,ht}$ > $T_{hs}$ + 5K） | 统计 $\eta_{p2p}$ 最优解的 $T_{st,ht}$ 分布 |
| H5 | R134a 作为 ORC 制冷剂时 $\Delta T_{sp}$ 的实际上限低于其他制冷剂（临界温度约束） | 统计各 ORC 制冷剂对应的 $\Delta T_{sp}$ 最大值分布 |

---

## 9. 小结

DC-A 工况下三目标冲突的根本来源是**热储温度跨度 $\Delta T_{st,sp}$ 的最优方向冲突**：

- $\eta_{p2p}$ 与 $\eta_{ex}$ 同需小 $\Delta T_{sp}$ ≈ 15–19K → **结构性协同**（基本构型下为正相关）
- $e_{th}$ 需大 $\Delta T_{sp}$ ≈ 60K → 与以上两者**均形成强冲突**，差距约 40–45K

构型对冲突结构的调节作用主要通过 **ORC 回热器**实现：通过引入替代提升路径，解耦 $\eta_{p2p}$–$\eta_{ex}$ 的设计空间，使冲突从正相关变为中性甚至负相关。制冷剂选择对冲突结构影响次要。

这一冲突格局与 Laterre 关于 $T_{TES}^{ht}$ 和 $\Delta T_{TES}^{sp}$ 作为卡诺电池性能的关键设计变量的阐释完全一致，同时也揭示了 DC-A 工况（位于 Laterre 临界点 $\Delta T_{hs-cs}$ = 30K）的过渡性特征。

---

*图表：`pure_deap_nsga/plots/conflict_*.png`*  
*数据：`pure_deap_nsga/plots/conflict_metrics_DC-A.csv`*  
*脚本：`pure_deap_nsga/analyze_conflict.py`*

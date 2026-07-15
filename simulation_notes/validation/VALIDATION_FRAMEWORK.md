# CBSim 模型可靠性验证框架 v1.0

制定日期：2026-06-24
基于：Laterre et al. (2024) Energy — Appendix B + Table 1 参数分类

---

## 0. 核心原则

**模型验证 ≠ 优化复现。** 模型验证要求给定完整循环参数后比较 KPI 误差；优化复现则允许在相同边界内搜索最优解。两者不可混淆。

Laterre 2024 Appendix B 报告的 `η_P2P = 39.7%`（原始约束）和 `η_P2P = 43.0%`（松弛约束）是**重新优化后最大化 η_P2P 的循环**，不是文献给出完整设计变量后的单点 benchmark。因此：
- **39.7%/43.0% 不属于 G1a（无优化单点验证）**
- **39.7%/43.0% 属于 G1b（优化复现目标）**

---

## 1. Gate 定义

### G1a：热力学模型单点可靠性验证

| 属性 | 说明 |
|------|------|
| **目的** | 给定相同循环配置参数，比较 CBSim 与参考结果的 KPI 误差 |
| **是否允许优化** | **否** — 所有设计变量必须由参考来源给定 |
| **输入要求** | 完整的边界条件 + 固定模型参数 + **全部**设计变量值 |
| **通过标准** | KPI 相对误差 < 5%（η_P2P, COP, η_ORC 等） |
| **当前状态** | ❌ 无合格 G1a case — 缺少完整设计变量集 |

**G1a 准入条件（必须全部满足）：**
1. 参考来源明确（文献 + 位置）
2. 边界条件完整（T_hs, T_cs）
3. 固定模型参数完整（pinch, 效率, 过冷度等）
4. **全部设计变量有给定值**（T_st_ht, dT_st_sp, dT_hp_cs_gl, dT_hp_ev_sh, dT_he_ev_sh, dT_hp_cd_sc, eta_max_cp, eta_max_ex, eta_pm, 工质对）
5. 预期 KPI 有明确数值

若条件 4 不满足，case 必须标记为 `incomplete_inputs_not_valid_for_G1a`。

### G1b：Laterre 优化结果复现

| 属性 | 说明 |
|------|------|
| **目的** | 在相同边界、变量范围和约束下，通过优化搜索验证能否接近 Laterre 的 39.7%/43.0% |
| **是否允许优化** | **是** — 需要单目标/多目标优化搜索 |
| **输入要求** | 边界条件 + 约束条件 + 变量范围（来自 Laterre Table 1 + Appendix B） |
| **通过标准** | 优化得到的 max η_P2P 在 Laterre 报告值的 5% 以内 |
| **当前状态** | 🔲 尚未启动 — 需单目标优化脚本 |

**Laterre Appendix B 两组约束：**

| 参数 | 原始约束 | 松弛约束 |
|------|---------|---------|
| t_hs | 50°C | 50°C |
| t_cs | 30°C | 30°C |
| t_st,ht^max | 150°C | 200°C |
| t_hp^max | 180°C | 300°C |
| p_st | 7.5 bar | 20 bar |
| Laterre 报告 η_P2P | 39.7% | 43.0% |

### G2：热力学趋势验证

| 属性 | 说明 |
|------|------|
| **目的** | 验证 CBSim 在关键参数扫描下的趋势与文献一致 |
| **是否允许优化** | **否** — 参数扫描（sweep），不用优化算法 |
| **输入要求** | 固定其他变量，扫描 1-2 个关键变量 |
| **通过标准** | 趋势方向与文献定性一致（如 T_st_ht↑ → η_P2P 先升后降） |
| **当前状态** | 🔲 尚未启动 |

**G2 推荐扫描维度：**
1. T_st_ht 对 η_P2P 的影响（验证 30K tipping point）
2. dT_st_sp 对 η_P2P 和 energy_density_thermal 的 trade-off
3. 约束松弛（p_st 从 7.5→20 bar）的性能变化方向

---

## 2. 已有证据归类

| 证据 | 原归类 | 新归类 | 说明 |
|------|--------|--------|------|
| `laterre_runner.py` 输出 | G1 验证 | **`interface_check`** | 构造点可运行检查，不满足 G1a 输入完整性要求 |
| `test_optimizer.py` 4/4 通过 | — | **G3 基础接口** | DEAP/NSGA-II 在当前环境可用 |
| Laterre 39.7% | G1 单点验证目标 | **G1b 优化复现目标** | 是优化结果，非给定参数的 benchmark |
| Laterre 43.0% | G1 单点验证目标 | **G1b 优化复现目标** | 同上 |
| DC-A test_optimizer 输出 | — | **G3 一致性检查** | eta_P2P=0.249 在 DC-A 合理范围 |

---

## 3. 验证层级与脚本标注

所有验证脚本必须在文件头或 README 中明确标注其验证层级：

| 标注 | 含义 | 允许优化 | 示例 |
|------|------|---------|------|
| `interface_check` | CBSim 接口可调用性检查 | 否 | `laterre_runner.py` |
| `single_point_validation` | G1a：固定参数单点 KPI 对比 | **否** | (待创建) |
| `optimization_reproduction` | G1b：优化复现 Laterre 目标 | 是 | (待创建) |
| `trend_validation` | G2：参数扫描趋势验证 | 否（仅扫描） | (待创建) |
| `optimizer_smoke_test` | G3：优化器基础接口测试 | 是（仅测试） | `test_optimizer.py` |

---

## 4. 验证 Case 数据结构（G1a）

每个 G1a case 必须以 JSON 格式提供，遵循 `single_point_case_template.json` 的结构：

- `source_reference`：文献来源和位置
- `configuration`：CB 构型（如 SBVCHP_SBORC_STES2T）
- `working_fluids`：HP 和 ORC 工质
- `boundary_conditions`：T_hs, T_cs 及其不确定度
- `fixed_model_parameters`：pinch, 效率, 过冷度，压力损失等
- `cycle_design_parameters`：**全部** 9 维设计变量值
- `expected_kpis`：参考 KPI 及其来源
- `tolerances`：各 KPI 的允许误差范围
- `verification_status`：`verified` / `incomplete_inputs_not_valid_for_G1a` / `pending`

**关键约束**：若 `cycle_design_parameters` 不完整，`verification_status` 必须为 `incomplete_inputs_not_valid_for_G1a`。

---

## 5. 后续路线图

| 优先级 | 任务 | Gate | 依赖 |
|--------|------|------|------|
| P0 | 寻找或构造真正 G1a 单点 benchmark case | G1a | 文献阅读员扫描 |
| P1 | 开发单目标优化脚本对标 Laterre 39.7%/43.0% | G1b | G3 已通 |
| P2 | T_st_ht 和 dT_st_sp 参数扫描趋势验证 | G2 | 脚本开发 |
| P3 | 多 seed NSGA-II 对照 | G3 | B 线启动 |

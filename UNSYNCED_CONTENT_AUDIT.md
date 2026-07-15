# 未同步内容功能与迭代版本整理

> 历史说明（2026-07-15）：本文档记录的 `pure_deap_nsga/_archive/`
> 已在仓库精简中删除，其脚本已被现行通用分析流程取代；
> 需查看旧实现时请使用 Git 历史。以下表格保留当时审计口径。

生成日期：2026-06-22

## 0. 总体判断

当前 `master` 与 `origin/master` 提交历史一致：本地没有已提交未推送的 commit，远程也没有本地未拉取的 commit。差异全部来自本地工作区：

- 已暂存：8 个旧全局 Pareto 绘图脚本移动到 `pure_deap_nsga/_archive/`。
- 未暂存：`pure_deap_nsga/deap_optimizer.py` 1 处目标函数口径修正、2 张旧图删除、4 个 `src/__pycache__/*.pyc` 缓存文件变化。
- 未跟踪：约 309 个路径，主要来自论文材料、近优/离设计点评估、本科论文、报告输出、缓存和系统文件。

从时间线看，项目内容已经经历四次明显迭代：

1. 2026-04-01：早期 LHS/扫描路线与基础 DEAP 结果。
2. 2026-04-07 至 2026-04-10：期刊论文 Part I，全局 Pareto、冲突指标、六工作点演化、假设验证。
3. 2026-05-19 至 2026-05-20：期刊论文 Part II/III，近优分析与 off-design 鲁棒性评估。
4. 2026-06-02 至 2026-06-03：本科论文材料与 manuscript 精简数据导出。

因此整理时不应简单按“新文件全部同步”。应按功能归档：主研究链条保留，运行缓存忽略，动态系统/早期扫描路线隔离或移出。

## 1. 主项目应同步内容

### 1.1 项目协作与总览文档

| 路径 | 功能 | 迭代状态 | 建议 |
|---|---|---|---|
| `AGENTS.md` | 7 角色 Agent 协作边界与文件所有权 | 当前协作规范 | 同步 |
| `CLAUDE.md` | 项目总览、目录树、命令、研究路线说明 | 当前项目说明，内容比 `AGENTS.md` 更完整 | 同步 |

这两个文件不是运行产物，属于项目恢复与后续协作的核心元数据。

### 1.2 优化器口径修正

| 路径 | 功能 | 迭代状态 | 建议 |
|---|---|---|---|
| `pure_deap_nsga/deap_optimizer.py` | DEAP 优化核心 | 本地仅改动 `Objectives.cop_hp()`：`cb.my_HP.COP_hp` 改为 `cb.my_HP.eta_hp_cyclen` | 需要验收后同步 |

该改动会影响 `cop_hp` 目标函数口径。它不是杂项文件，应通过 `test_optimizer.py` 或单工况快速测试验证后提交。

### 1.3 脚本归档整理

| 路径 | 功能 | 迭代状态 | 建议 |
|---|---|---|---|
| `pure_deap_nsga/_archive/README.md` | 说明归档脚本为何废弃 | 当前归档说明 | 同步 |
| `pure_deap_nsga/_archive/plot_global_pareto_DCB.py` 等 8 个脚本 | 单工作点/单目标组合的探索性全局 Pareto 绘图 | 已被 `build_global_pareto.py` 与更通用分析流程替代 | 保留在 `_archive/` 并同步 |
| `pure_deap_nsga/_archive/build_presentation.py` | 一次性组会 PPT 生成脚本 | 不可复用 | 可同步到 `_archive/`，或不提交 |

归档脚本本身已在 README 中标记“Do not import”。这批重命名是合理的整理动作。

## 2. 期刊论文分析链条

### 2.1 Part I：全局 Pareto、冲突与假设验证

| 路径 | 功能 | 迭代状态 | 最终版本判断 |
|---|---|---|---|
| `pure_deap_nsga/build_global_pareto.py` | 构建 DC-A 全局 Pareto，做 Interface I/II、`dT_st_sp` 中介与降维判断 | 2026-04-08 完成 | 替代 `_archive/plot_global_pareto_*.py` 中多数 DC-A 探索脚本 |
| `pure_deap_nsga/analyze_conflict.py` | 三目标冲突指标 | 2026-04-07 完成 | Part I 冲突分析主脚本 |
| `pure_deap_nsga/verify_H1.py` 至 `verify_H5.py` | 五个机理假设验证 | 2026-04-08 完成 | 可作为论文机制验证附属脚本 |
| `pure_deap_nsga/plot_six_wp_evolution.py` | 六工作点冲突/性能演化图 | 2026-04-10 完成 | 六工况对比最终图脚本 |

这组脚本大多已被 Git 跟踪，未跟踪新增重点是 `plot_six_wp_evolution.py` 与生成图 `plots/global_pareto/six_wp_evolution.png`。

### 2.2 Part II：近优设计分析

| 路径 | 功能 | 迭代状态 | 最终版本判断 |
|---|---|---|---|
| `pure_deap_nsga/near_optimal_analysis.py` | 近优区域、must-have/real-choice 参数分类、构型/工质竞争、代表设计 | 2026-05-19 完成，手册标记“已完成” | Part II 最终脚本 |
| `pure_deap_nsga/near_optimal_analysis_使用手册.md` | 方法与输出说明 | 2026-05-20 完成 | 应与脚本同步 |
| `pure_deap_nsga/results/near_optimal_*` | 每工况参数 CV、代表设计、跨工况汇总 | 由脚本生成，6 个工作点齐全 | 可同步为论文复现实验结果 |
| `pure_deap_nsga/plots/near_optimal/*` | 近优分析图 | 与结果同步生成 | 可同步，或按仓库策略只保留 CSV 不保留图 |

最终结论来自手册中的自述：该脚本完成“全局 Pareto 汇聚 → 3D 非支配排序 → 近优区域定义 → 代表设计选取 → 出图”的完整流程。

### 2.3 Part III：Off-design 鲁棒性评估

| 路径 | 功能 | 迭代状态 | 最终版本判断 |
|---|---|---|---|
| `pure_deap_nsga/off_design_eval.py` | 季节对边界条件下的非设计点评估 | 2026-05-20 完成，手册标记“已完成” | Part III 最终脚本 |
| `pure_deap_nsga/off_design_eval_使用手册.md` | 方法、参数、输出说明 | 2026-05-20 完成 | 应与脚本同步 |
| `pure_deap_nsga/results/off_design_eval.csv` | 36 个名义/非设计点评估点 | 最终输出 | 可同步 |
| `pure_deap_nsga/results/off_design_retention.csv` | 15 对性能保持率 | 最终输出 | 可同步 |
| `pure_deap_nsga/plots/off_design/*` | 鲁棒性图 | 最终输出 | 可同步或按图表策略处理 |

该模块依赖 `near_optimal_{WP}_designs.csv`，所以同步时应保证 Part II 结果先存在。

## 3. Manuscript 精简数据导出

| 路径 | 功能 | 迭代状态 | 建议 |
|---|---|---|---|
| `paper_outputs/aggregate_pareto_stdlib_for_manus.py` | 不依赖 pandas 的 manuscript 精简 Pareto 导出脚本 | 2026-06-03 生成 | 同步，优先于根目录旧版 |
| `paper_outputs/pareto_front_global_reduced.csv` | 每工作点采样后的全局非支配前沿，1080 行 | 由上脚本生成 | 可同步 |
| `paper_outputs/pareto_front_by_config_reduced.csv` | 构型级前沿采样，1440 行 | 由上脚本生成 | 可同步 |
| `paper_outputs/pareto_source_summary.csv` | 24 个 `WP × config` 汇总 | 由上脚本生成 | 可同步 |
| `aggregate_pareto_for_manus.py` | 根目录 pandas 版导出脚本 | 与 `paper_outputs` 版功能重复，较早/较不便携 | 建议移入 `_archive/` 或不提交 |
| `paper_outputs/write_test_marker.txt` | 写入权限测试标记 | 非研究数据 | 删除或忽略 |

`paper_outputs` 是从 `pure_deap_nsga/results` 中抽取的轻量结果，不是新的优化源数据。

## 4. 论文与文献材料

### 4.1 期刊论文路线

| 路径 | 功能 | 迭代状态 | 最终版本判断 |
|---|---|---|---|
| `paper/期刊论文初稿大纲（v2.0）.md` | 旧路线：包含 Lorenz/动态仿真/CSWD 等动态系统内容 | 已过时 | 不建议作为当前路线同步，或标记 obsolete |
| `paper/期刊论文初稿大纲（v3.0）.md` | 当前路线：稳态优化、近优、off-design 三部分 | 2026-05-14 更新 | 当前期刊论文大纲最终版 |
| `paper/文献锚定方案_M2.md` | 11 篇核心文献与仿真设计决策锚定 | 2026-05-19 更新 | 同步 |
| `paper/待获取文献清单.md` | 文献追踪 | 2026-05-20 更新 | 同步 |

动态系统建模已经切割出去后，`v2.0` 中的动态性能评估、8760 仿真、中国气象数据等内容应视为旧路线。

### 4.2 Li 2024 文献解析目录

| 路径 | 功能 | 迭代状态 | 建议 |
|---|---|---|---|
| `paper/Li 等 - 2024 - .../full.md` | Li 2024 论文文本解析 | 2026-05-19 生成 | 可同步，若仓库允许文献解析材料 |
| `paper/Li 等 - 2024 - .../*_origin.pdf` | 原始 PDF | 大文件，版权/体积敏感 | 不建议提交到 Git |
| `paper/Li 等 - 2024 - .../images/*`、`layout.json`、`model.json`、`block_list.json` | PDF 解析中间产物 | 工具生成物 | 不建议提交，除非建立专门文献资产目录 |

建议只保留可引用的 Markdown 摘要/笔记，不把 PDF 解析中间产物全部同步。

## 5. 本科论文材料

`undergraduate_thesis/` 是 2026-06-02 形成的一套独立交付物。它复用了主项目优化结果，但面向本科毕业设计，不是期刊主线代码。

### 5.1 功能分组

| 路径 | 功能 | 迭代状态 | 建议 |
|---|---|---|---|
| `undergraduate_thesis/undergraduate_config.json` | 本科论文配置 | 最终配置 | 若保留本科论文模块则同步 |
| `undergraduate_thesis/utils.py` | 本科分析工具函数 | 最终工具 | 同步 |
| `undergraduate_thesis/config_fluid_comparison.py` | 第3章构型/工质对比 | 最终分析脚本 | 同步 |
| `undergraduate_thesis/param_sweep.py` | 第4章参数扫描 | 最终分析脚本 | 同步 |
| `undergraduate_thesis/sensitivity_analysis.py` | Morris/敏感性分析 | 最终分析脚本 | 同步 |
| `undergraduate_thesis/exergy_analysis.py` | 㶲损失分析 | 最终分析脚本 | 同步 |
| `undergraduate_thesis/analyze_undergrad_pareto.py` | 第5章 Pareto 分析 | 最终分析脚本 | 同步 |
| `undergraduate_thesis/plot_ts_diagrams.py` | 第2章 T-s 图 | 最终绘图脚本 | 同步 |
| `undergraduate_thesis/optimize_undergrad.py`、`undergraduate_runner.py` | 本科论文优化/执行入口 | 初始运行脚本 | 可同步，但需说明与主 DEAP 流程关系 |

### 5.2 论文稿件迭代链

| 路径 | 角色 | 状态 |
|---|---|---|
| `undergraduate_thesis/thesis_draft.md` | 初稿 | 被大修稿替代 |
| `undergraduate_thesis/thesis_major_revised.md` | 大修稿 | 被小修稿替代 |
| `undergraduate_thesis/thesis_minor_revised.md` | 小修后返修稿 | 当前最终 Markdown |
| `undergraduate_thesis/thesis_draft.docx` | 初稿 DOCX | 非最终 |
| `undergraduate_thesis/minor_revision_summary.md` | 小修说明 | 当前最终修改说明 |

当前未看到 `thesis_minor_revised.docx` 出现在工作区，虽然小修说明中提到该文件。若需要 Word 最终稿，需要重新生成或找回。

### 5.3 数据重复关系

`undergraduate_thesis/results/chapter5/all_pareto_combined.csv` 与 `pure_deap_nsga/results/all_pareto_combined.csv` 内容完全相同。因此它是主结果的副本，不是新的计算结果。同步时二选一即可，建议本科目录中保留轻量说明或软引用，避免重复 5.1 MB 数据。

`undergraduate_thesis/results/chapter5/_quick_run_backup/` 是 DC-C 快速运行备份，每个文件 80 行，属于中间备份；不建议作为最终数据同步。

## 6. 动态系统与早期扫描残留

### 6.1 `simulation_notes/`

`simulation_notes/` 目前包含两类内容：

1. 2026-04-01 早期 Pareto/LHS 扫描路线：`dc_pareto_scan.py`、`pareto_frontier_scan.py`、`dc_config.json`、`results/*`、`figs/dc_*`。
2. 2026-04-24 动态/转速调节复现：`plot_shaft_speed_regulation.py`、`plot_shaft_zhang2020_replica.py`、`plot_shaft_zhang2020_v2.py`、`figs/shaft_speed_*.png`。

前者已被 `pure_deap_nsga` 的 DEAP/NSGA-II 主路线替代；后者属于已经切割出去的动态系统建模方向。

建议：

- 不再新增同步 `simulation_notes` 的 2026-04-24 shaft-speed 文件。
- 对已跟踪的早期 `simulation_notes`，后续可单独开清理提交：移入外部归档仓库或标记 `legacy/`。
- 如果当前目标是“主项目 GitHub 同步”，这部分应排除。

### 6.2 `opt/RHEIA/`

`opt/RHEIA/` 是外部优化框架/早期复现路线，项目说明中已标记“参考，非主用”。当前未同步新增主要只有 `opt/.DS_Store`，应忽略。不要再把 RHEIA 运行产物扩展进主同步范围。

## 7. 明确应忽略或删除的内容

| 类型 | 路径示例 | 原因 | 建议 |
|---|---|---|---|
| macOS 系统文件 | `.DS_Store`、`pure_deap_nsga/.DS_Store`、`paper/.DS_Store` | 系统缓存 | 加入 `.gitignore`，不提交 |
| Python 缓存 | `src/__pycache__/*.pyc`、`pure_deap_nsga/__pycache__/*`、`undergraduate_thesis/__pycache__/*` | 运行产物 | 从 Git 跟踪中移除并忽略 |
| PDF 解析中间产物 | `layout.json`、`*_model.json`、`images/*.jpg` | 大量工具生成物 | 不提交或迁移到文献资产库 |
| 临时测试文件 | `paper_outputs/write_test_marker.txt` | 权限测试 | 删除 |
| 压缩包 | `pareto_results_export.tar.gz` | 导出包，内容可能重复 | 不提交，必要时放 release/artifact |
| 旧图删除 | `pure_deap_nsga/plots/global_pareto/config_fluid_decomposition_DCE_p2p_etaex.png`、`..._eth.png` | 本地删除但同系列其他图仍在 | 需确认是否由新图替代后再提交删除 |

## 8. 建议同步批次

### 批次 A：仓库卫生

- 新增 `.gitignore`，覆盖 `.DS_Store`、`__pycache__/`、`*.pyc`、临时输出。
- 从 Git 跟踪中移除已有 `__pycache__/*.pyc`。
- 不触碰研究逻辑。

### 批次 B：项目元数据与归档

- 提交 `AGENTS.md`、`CLAUDE.md`。
- 提交 `_archive/README.md` 与 8 个脚本移动。
- 可选提交本整理报告。

### 批次 C：期刊论文分析新增模块

- 提交 `near_optimal_analysis.py`、`off_design_eval.py`、对应使用手册。
- 提交 `plot_six_wp_evolution.py`。
- 提交对应 CSV 结果；图表是否提交按仓库策略决定。

### 批次 D：论文与文献

- 提交 `paper/期刊论文初稿大纲（v3.0）.md`、`paper/文献锚定方案_M2.md`、`paper/待获取文献清单.md`。
- `v2.0` 标记旧路线或不提交。
- Li 2024 目录只提交必要 Markdown，排除 PDF 与解析中间产物。

### 批次 E：本科论文独立模块

- 若本科论文仍需随主仓库保存：提交 `undergraduate_thesis` 的最终脚本、最终 Markdown、小修说明、必要 CSV/图。
- 排除 `__pycache__`、`.DS_Store`、`_quick_run_backup` 和重复的 `all_pareto_combined.csv`。

## 9. 最终版本速查

| 功能 | 最终版本 |
|---|---|
| 主优化入口 | `pure_deap_nsga/run_optimization.py` |
| 优化核心 | `pure_deap_nsga/deap_optimizer.py`，但需验证本地 `cop_hp` 口径改动 |
| 全局 Pareto/冲突机制 | `pure_deap_nsga/build_global_pareto.py` + `analyze_conflict.py` + `verify_H1.py` 至 `verify_H5.py` |
| 六工作点演化图 | `pure_deap_nsga/plot_six_wp_evolution.py` |
| 近优分析 | `pure_deap_nsga/near_optimal_analysis.py` |
| Off-design 分析 | `pure_deap_nsga/off_design_eval.py` |
| Manuscript 精简导出 | `paper_outputs/aggregate_pareto_stdlib_for_manus.py` |
| 当前期刊论文大纲 | `paper/期刊论文初稿大纲（v3.0）.md` |
| 文献锚定 | `paper/文献锚定方案_M2.md` |
| 本科论文最终 Markdown | `undergraduate_thesis/thesis_minor_revised.md` |
| 已切割/不作为主线 | `simulation_notes/plot_shaft_*.py`、`simulation_notes/figs/shaft_speed_*.png`、`paper/期刊论文初稿大纲（v2.0）.md` 中动态仿真路线 |

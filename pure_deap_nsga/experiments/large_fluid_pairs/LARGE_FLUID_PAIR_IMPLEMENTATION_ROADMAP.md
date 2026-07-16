# 大规模工质对计算能力补齐方案 v1.0

## 1. 目标与当前差距

目标是在 12×12 工质候选池上安全执行 P0/P1、S0–S5 分阶段计算，并使任一 Pareto 点、
空前沿或求解失败都能独立复现和审计。

当前 `master` 已提供候选配置、初步预筛、优化器、诊断对象和失败 Schema，但正式批处理
仍缺少以下闭环：

```text
任务定义 -> 隔离执行 -> 流式诊断 -> 检查点 -> 原子输出
        -> 完整性验收 -> 批次台账 -> 跨 seed 收敛判定
```

本方案是实现路线图，不表示相应功能已经完成。`optimization_config_large_pairs.json` 中的
`status=template_not_approved_for_full_run` 在所有强制门通过前应保持不变。

## 2. 设计原则

1. 最小任务固定为 `WP × configuration × HP fluid × HE fluid × seed`。
2. runner 只负责执行一个任务；批量展开由独立 planner/scheduler 完成。
3. JSON/Parquet 为权威结构化数据，CSV 用于轻量索引和人工检查。
4. 所有写入面向仓库外的 `data_root/run_id`，不再依赖全局 `results/`。
5. 失败诊断必须流式落盘，不能只留在进程内存中。
6. 计算完成和结果有效是两个不同判定；程序退出码 0 不自动等于验收通过。

### 2.1 已确认的阻断缺陷

在扩大实验前还必须处理以下优化层问题：

- 明确 `cxpb`、个体级 `mutpb` 和基因级 `indpb`；即使个体未发生交叉，也必须允许 mutation-only 路径；
- 当前种群修正规则不能保证任意输入都成为 4 的倍数，应使用 `ceil(pop/4)*4` 或直接拒绝非法值；
- NSGA-III 若仍复用不匹配的子代选择逻辑，应先禁用或完成独立验收，不能仅因配置名存在就宣称支持；
- 可行性必须检查全部目标的 finite/penalty 状态，不能只依赖第一个目标；
- Pareto front 必须按固定容差去重，并同时保留原始规模；
- 旧 Pareto 审计脚本含原始 4 工质假设，扩展池验收前必须参数化或替换；
- `diagnostics_enabled=false` 与正式失败数据契约冲突，正式阶段必须启用可持久化诊断。

## 3. 目标命令行接口

建议将 `run_optimization.py` 扩展为兼容旧参数的新接口：

```text
--config PATH                 必填或使用明确默认值；不存在时立即失败
--wp KEY                      单工况
--cfg KEY                     单构型
--fluid-hp NAME               单 HP 工质
--fluid-he NAME               单 HE 工质
--pair-list PATH              与单工质参数互斥
--seed INTEGER                随机种子
--run-id STRING               唯一运行标识
--output-dir PATH             独立输出目录
--resume-from PATH            检查点恢复
--checkpoint-every INTEGER    检查点间隔
--diagnostics {off,failures,all}
--fail-fast                   仅用于配置错误，不用于单点评价失败
```

配置路径不存在时不得静默回退到 `simulation_notes/dc_config.json`。启动时应把解析后的实际
配置、参数和输出目录打印到日志并写入 manifest。

## 4. 工作包和实现顺序

### WP0：基线冻结和回归 fixture

**Owner**：验收测试 + 优化设计师。

工作内容：

- 固定当前 4×4 工质池中的代表 WP/构型/工质对；
- 保存可行解、空前沿和典型求解失败 fixture；
- 固定输出列、变量顺序、目标方向和容差；
- 增加 config-path 不存在时必须失败的测试。

验收：现有 4/4、6/6、9/9 测试继续通过；固定输入在受支持环境中可复算。

### WP1：优化器正确性

**Owner**：优化设计师 + 验收测试。

工作内容：

- 修正交叉、个体变异和基因变异的概率语义；
- 保证 mutation-only 路径被实际评价；
- 修正种群规模 4 倍数规则；
- 对全部目标执行 finite/penalty 判定；
- 固定前沿去重规则；
- 完成 NSGA-III 的匹配实现和测试，或在 CLI 中显式拒绝。

验收：`cx=0, mut=1` 的合成测试仍产生并评价变异子代；101 自动调整为 104 或被明确拒绝；
同 seed 输出可复现；NaN、Inf 或任一目标罚值不得进入前沿。

### WP2：任务模型、run-id 和输出隔离

**Owner**：优化设计师。

工作内容：

- 增加 `RunSpec`/`RunContext` 数据结构；
- 实现目标 CLI、输出目录和唯一 run-id；
- 每任务生成配置快照、manifest、command 和环境信息；
- 增加目录锁，拒绝两个进程写同一任务目录；
- 保持旧命令可用，但打印弃用提示。

验收：两个不同 seed 同时运行不会覆盖；相同 run-id 的第二个进程拒绝启动；配置路径错误
不会回退；所有输出仅出现在指定目录。

### WP3：工质对选择和批次展开

**Owner**：优化设计师 + 调用计算员。

工作内容：

- 支持 `--fluid-hp/--fluid-he` 和 `--pair-list`；
- 新增批次 planner，把 P1 合格表展开为不可变任务清单；
- 任务清单包含 run-id、命令、资源请求和预期输出；
- 为 Slurm/PBS/本地进程池生成 array-job 输入，但不在 worker 内嵌调度逻辑。

验收：展开任务数等于显式笛卡尔积减去 gate 排除项；重复 run-id、未知工质或未通过 gate
的组合在启动前失败；单任务只运行指定工质对。

### WP4：P0/P1 预筛补全

**Owner**：构型设计师 + 优化设计师。

当前 `probe_fluid_pairs.py` 只覆盖 CoolProp 核心常数与 Tc margin。需要补充：

- 边界饱和态可查询性；
- 三相点/冻结裕量；
- 工作压力窗口、压比和排气温度预估；
- 配置值与 CoolProp 值差异检查；
- P2 的 ODP、GWP100 来源/年份、安全等级、可燃/毒性、稳定性和法规元数据；
- `engineering`、`exploratory`、`excluded` 三类结论及可审计原因码。

验收：每个工质和每个 WP×工质对都有明确 gate 状态；缺失工程属性不能默认通过；预筛
输出带 manifest、配置哈希、数据来源版本和校验和。

### WP5：S0/S1 采样执行器

**Owner**：优化设计师 + 建模工程师。

工作内容：

- 实现中位设计点 S0 烟测；
- 实现可复现的 scrambled Sobol 或 LHS，保存 sampler 和 seed；
- S1 每对默认 256 点，保存九维输入、可行性、KPI 和 failure_id；
- 输出 `sampling_feasibility.parquet` 和工质对失败谱摘要；
- 0/256 只报告可行率上界，不自动判物理不可行。

验收：相同 seed 生成相同样本；样本在边界内且无重复；输入行数、评价数和失败记录数可
对账；中断后不会留下被误认为完成的正式文件。

### WP6：失败诊断流式落盘

**Owner**：建模工程师 + Bug 反馈工程师。

工作内容：

- 将 `CBEvaluator.diagnostics_records` 接入持久化 writer；
- 按 `failure_record.schema.json` 保存一次评价一个 JSON；
- 保存求解 `x0/bounds/x_final`、残差向量、迭代状态和 fallback 链；
- 保存最后有效状态点和失败 PropsSI 输入；
- 生成三张关联索引表；
- 收紧 Schema 的 stage/code 枚举、时间和哈希格式，并增加跨字段语义校验；
- 对异常链中可能包含的绝对路径或敏感环境值做最小化处理。

验收：构造配置、物性、压力求解、质量流量、回热器、守恒和包装层失败各至少一个 fixture；
JSON 通过 Schema 校验；索引外键完整；进程异常终止前已完成的诊断仍可读取。

### WP7：检查点、恢复和原子写

**Owner**：优化设计师。

工作内容：

- 保存种群、适应度、随机数状态、当前代、Pareto archive 和诊断计数；
- 恢复时校验 commit、配置哈希、算法和变量定义；
- 所有 CSV/JSON/Parquet 先写 `.tmp`，fsync 后原子重命名；
- 检查点使用版本化 Schema，并保留最近两个有效版本。

验收：在固定代数强制中断后恢复，最终结果与未中断同 seed 运行在规定容差内一致；损坏
检查点被拒绝且不会退回未知状态；终态目录无 `.tmp`。

### WP8：每代指标和收敛分析

**Owner**：优化设计师。

工作内容：

- 保存每代评价数、可行率、去重前沿规模、unique ratio、目标范围和 HV；
- 明确归一化方法和跨 seed 公共参考点；
- 实现 S3 候选池化、HV/极值覆盖排序；
- 实现 S4 的 HV CV、IGD+、极值 KPI CV 和 4/5 seed 稳定性报告。

验收：指标由原始前沿可重算；结果不依赖输入文件顺序；未通过多 seed 门时不得输出
“稳定推荐”。

### WP9：资源监控、台账和批次汇总

**Owner**：调用计算员 + 验收测试。

工作内容：

- 保存 CPU 时间、峰值 RSS、磁盘和墙钟时间；
- worker 仅写自己的 manifest，汇总器单写 `run_registry.csv`；
- 实现 `PLANNED/RUNNING/CHECKPOINTED/COMPLETED/EMPTY/FAILED/TIMEOUT/CANCELLED` 状态机；
- 批次报告列出完成率、空前沿率、失败谱、资源消耗和待重跑任务。

验收：台账 run-id 唯一；状态迁移合法；任一任务可从台账定位到 manifest、日志、输出和
失败记录；聚合计数与各任务 manifest 总和一致。

### WP10：S5 独立物理复算和正式放行

**Owner**：建模工程师 + 验收测试。

工作内容：

- 每 WP 选择效率、密度和折中代表点；
- 不读取优化器缓存，使用原求解器独立构造并复算；
- 检查能量/火用守恒、相态、pinch、压力和 KPI；
- 生成代表点证据表和最终放行报告。

验收：代表点全部通过物理守门；失败点回链到原 run/evaluation；只有通过 P0–P2、S4 和
S5 的组合才可标记为工程推荐。

## 5. 建议文件布局

```text
pure_deap_nsga/
├── run_optimization.py                 # 单任务 runner
├── batch/
│   ├── plan_runs.py                    # 任务展开
│   ├── summarize_runs.py               # 台账/批次汇总
│   └── validate_run.py                 # 单任务完整性验收
├── runtime/
│   ├── run_context.py                  # RunSpec、manifest、锁和状态机
│   ├── atomic_io.py
│   ├── checkpoint.py
│   └── diagnostic_writer.py
├── sampling/
│   └── feasibility_screen.py            # S0/S1
└── experiments/large_fluid_pairs/
    ├── README.md
    ├── COMPUTE_RUN_DATA_MANAGEMENT_SPEC.md
    ├── LARGE_FLUID_PAIR_IMPLEMENTATION_ROADMAP.md
    ├── optimization_config_large_pairs.json
    ├── failure_record.schema.json
    ├── run_manifest.schema.json          # 待实现
    └── probe_fluid_pairs.py
```

## 6. 里程碑和放行门

| 里程碑 | 包含工作包 | 允许执行范围 | 强制放行条件 |
|---|---|---|---|
| M0 基线可复现 | WP0 | 当前小池回归 | 所有现有测试和 fixture 通过 |
| M1 优化器正确 | WP1 | 受控小池优化 | 变异、种群、目标判定和去重通过 |
| M2 运行隔离 | WP2–WP3 | 单 worker/多 worker 烟测 | 无覆盖、锁和 manifest 通过 |
| M3 预筛完整 | WP4–WP5 | P0/P1/S0/S1 | gate、采样和计数完整 |
| M4 失败可审计 | WP6 | S1 诊断批次 | Schema、索引、流式留存通过 |
| M5 可恢复优化 | WP7–WP9 | S2/S4 批次 | 恢复、原子写、指标和台账通过 |
| M6 物理确认 | WP10 | S5/最终推荐 | 独立复算和多 seed 门通过 |

任何里程碑未通过时，只能执行该里程碑允许范围内的调试任务，不能提前扩大规模。

## 7. 测试矩阵

至少新增以下自动化测试：

1. CLI 参数组合、未知 WP/构型/工质、错误配置路径；
2. 两 seed 输出隔离和同 run-id 锁冲突；
3. manifest Schema、状态迁移和原子写中断；
4. pair-list 去重、gate 拒绝和任务数守恒；
5. Sobol/LHS 确定性、边界和样本唯一性；
6. 失败 JSON Schema 与三索引外键；
7. 检查点损坏、版本不匹配和中断恢复；
8. Pareto 去重、HV/IGD+ 重算和输入顺序不变性；
9. EMPTY 与 FAILED 分类；
10. 8 worker 并发烟测，无共享文件写入和结果覆盖。

## 8. 资源和执行策略

先运行 8 个代表任务的并发基准，测量 CoolProp 调用竞争、CPU 利用率、峰值内存和 I/O。
在没有基准证据前，并行度上限设为 8 个隔离 worker。预计 S1+S2+S4 串行约 139 h；
8 worker 的墙钟预算按 22–28 h 预留，而不是使用理想线性加速值承诺完成时间。

调度优先级：P0/P1 → S0 → S1 → S2 → S3 → S4 → S5。任何阶段的失败谱出现新的高频
未知根因时，暂停扩大规模，先增加 fixture、分类和复现用例。

## 9. 完成定义

只有同时满足以下条件，才可把大规模工质对能力标记为“正式可用”：

- WP0–WP10 验收全部通过；
- `optimization_config_large_pairs.json` 状态由独立验收提交改为 approved；
- 8 worker 并发烟测无覆盖或锁冲突；
- 任意输出可由 run-id 回溯全部输入和环境；
- 任意失败可由 evaluation-id 定位到求解参数、状态和异常链；
- 任意 S4 推荐具有 5-seed 稳定性证据；
- 任意工程推荐通过 P2 和 S5 独立复算。

在此之前，12×12 池的输出只能标记为探索性结果。

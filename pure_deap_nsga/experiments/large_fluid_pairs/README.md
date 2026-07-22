# 大规模工质对优化升级方案 v0.1

## 执行文档

- [`COMPUTE_RUN_DATA_MANAGEMENT_SPEC.md`](COMPUTE_RUN_DATA_MANAGEMENT_SPEC.md)：计算平台初始化、轮次拆分、run-id、目录、manifest、状态机、失败记录和验收规范。
- [`LARGE_FLUID_PAIR_IMPLEMENTATION_ROADMAP.md`](LARGE_FLUID_PAIR_IMPLEMENTATION_ROADMAP.md)：从当前 runner 到可执行大规模并行工质对计算的能力补齐路线图。

> `optimization_config_large_pairs.json` 已在 S0/S1DEV、原生崩溃修复、第二 Sobol seed、
> 1024 点稀疏域复核和诊断闭环验收后批准用于正式 S1。S2–S4 正式优化仍须通过 M5。

## 隔离式大规模 runner

`run_large_scale.py` 将最小任务固定为
`WP × configuration × HP fluid × HE fluid × seed`，支持单工质对、CSV pair-list、
多 seed、任务级多进程、独立 run-id、目录锁、原子输出、代检查点、恢复、跨代
Pareto archive、失败 JSON/CSV 索引和前沿物理验收。

S2 优化使用配置中冻结的目标归一化域和参考点逐代计算 normalized
hypervolume。当前预生产/正式门设置为最多 300 代、至少 150 代；只有连续 5 代均满足
“相对 20 代前的 HV 改善小于 0.5%”才提前停止。归一化域越界会作为配置/科学错误
终止任务，不进行动态缩放或静默裁剪。

优化 archive 不直接作为科学前沿发布。每个任务结束后会由两个独立 Python/CoolProp
子进程复算全部 raw archive；任一次不可行或两次 KPI 超容差不一致的点进入
`front_quarantine.csv`。两次稳定的点以复算 KPI 重新进行非支配筛选，权威结果写入
`pareto.csv`，完整历史和复验台账分别保存在 `pareto_archive_raw.csv` 与
`front_revalidation.csv`。

开发验收示例：

```bash
../.venv/bin/python pure_deap_nsga/experiments/large_fluid_pairs/run_large_scale.py \
  --config pure_deap_nsga/experiments/large_fluid_pairs/optimization_config_large_pairs.json \
  --data-root /path/outside/repository/cbsim-runs \
  --stage DEV --wp DC-A --cfg SBVCHP_SBORC \
  --fluid-hp 'R1233zd(E)' --fluid-he 'R1234ze(E)' \
  --seed 42 --population-size 48 --generations 50 \
  --checkpoint-every 10 --workers 1
```

pair-list 必须包含 `fluid_hp,fluid_he` 两列。多个 worker 只并行不同的最小任务；
单任务内部仍串行，避免在线程间共享 CoolProp 状态。原生崩溃、普通异常和超时分别写入
任务 manifest、日志和唯一终态文件。

正式 `S1`–`S5` 同时要求：

- Git 工作树干净；
- `experiment.status=approved_for_full_run`；
- 工质对通过 Tc、三相点、饱和物性、压力窗口和估算压比门。

精细前沿参数位于 `experiment.profiles.S6_fine_front`。超过 1000 点依赖跨代 archive
及多 seed 合并，不由末代种群规模单独保证；该 profile 只应用于已经通过 S4 的少量组合。

## 1. 目标

在不将“数值不收敛”误判为“热力学不可行”的前提下，将当前
4 HP 工质 × 4 HE 工质扩展为 12–15 × 12–15 的原始候选池，通过分阶段
successive-halving 流程筛选到可用于多 seed 确认优化的小型高价值工质对集。

历史基线：224 个已执行合法组合，182 个非空前沿，总耗时 64,752.3 s，
约 289.1 s/组合。因此不应直接对扩展池做全量 100×150 NSGA-II。

## 2. 执行前必须补齐的运行能力

1. 按 `run_id/seed` 隔离结果、日志和 manifest，禁止多 seed 覆盖。
2. runner 支持 pair-list、断点续跑、completed/empty/failed 三态和原子写入。
3. 保存每代可行率、去重前沿规模、hypervolume 和资源使用。
4. 按 `failure_record.schema.json` 流式保存失败评价；主前沿表只保存 `failure_id`。
5. 修正并验证 NSGA-II 个体变异率/基因变异率语义后再执行正式批次。

## 3. 工质候选池与分层门

`optimization_config_large_pairs.json` 包含 12 HP 和 12 HE 候选工质。扩展工质
默认标记为 `exploratory`，不代表已通过安全、环境或设备适用性审批。

| Gate | 检查 | 输出 |
|---|---|---|
| P0 物性可用性 | CoolProp 规范名，`Tcrit/Pcrit/Ttriple`，边界饱和态可查询 | `fluid_catalog.csv` |
| P1 热力学预检 | 临界温度裕量、三相点/冻结、压力窗口、压比、排气温度 | `pair_eligibility.csv` |
| P2 工程属性 | ODP、GWP100 来源/年份、ASHRAE 安全等级、可燃/毒性、热稳定和法规 | engineering/exploratory 分池 |

P0/P1 可先用：

```bash
../.venv/bin/python pure_deap_nsga/experiments/large_fluid_pairs/probe_fluid_pairs.py \
  --config pure_deap_nsga/experiments/large_fluid_pairs/optimization_config_large_pairs.json \
  --output pair_eligibility.csv
```

## 4. 分阶段计算设计

| 阶段 | 设计 | 去留规则 | 估算计算量 |
|---|---|---|---:|
| S0 单点烟测 | 每工质×侧×6 WP，中位设计变量，SB/SR 各至少 1 构型 | 异常全记录，不直接判物理不可行 | 低 |
| S1 可行域筛查 | DC-B/D/F×SB-SB/SR-SR，每对 scrambled Sobol/LHS 256 点 | 按可行率+失败码分层；0/256 只表示可行率 95% 上限约 1.17% | 144 对约 221k evaluations，约 2.9 h 串行 |
| S2 粗优化 | 每 WP 前 30–40 对，6 WP×4 构型，pop=48、gen=50、seed=42 | 可行率+目标覆盖+HV 贡献 | 40 对约 2.12M evaluations，约 28 h 串行 |
| S3 复筛 | 按 WP×已验收构型池化认证前沿 | 每单元前 5 对；同时覆盖效率/密度/火用极值 | 后处理 |
| S4 确认优化 | 6 WP×4 构型×5 对×5 seeds，pop=100、gen=150 | 通过多 seed 收敛门 | 约 8.16M evaluations，约 108 h 串行 |
| S5 独立复算 | 每 WP 效率/密度/折中 3 代表点 | 原求解器复算+能量/火用/相态守门 | 低 |

S1+S2+S4 串行估算约 139 h。8 个隔离 worker 理想值约 17.4 h，考虑
I/O、不均衡和性质调用竞争，墙钟预留 22–28 h。并行前先做 8 任务基准。

## 5. 收敛和验收门

### 单运行

- front 非空；末代可行个体占比默认 `>=20%`（困难组合 `>=5%` 标黄）。
- 去重后 front `>=20` 点，unique ratio `>=90%`。
- 末 20 代归一化 HV 相对改善 `<0.5%`。

### 多 seed

- seeds：`[17, 42, 73, 101, 202]`。
- 相对公共参考前沿的 HV CV `<=5%`。
- 各 seed 到 union front 的归一化 IGD+ `<=0.03`。
- 三个极值 KPI 的跨 seed CV `<=3%`。
- 最终推荐工质对/构型应在至少 4/5 seeds 进入前列。

常规 S2 未过门时延长到 300 代或扩大种群，不得只选择表现最好的 seed。

S3 必须以冻结的 S2 `accepted_run_registry.csv` 为唯一输入，不得重新拼接 base 与
extension 批次。当前正式工具的选择顺序为：先以最少候选覆盖三个目标极值，再按候选
完整认证前沿对已选集合的 exact normalized-HV 增量补齐到 5 对；HV 并列按配置中冻结
的容差和稳定键裁决。示例：

```bash
.venv/bin/python \
  pure_deap_nsga/experiments/large_fluid_pairs/select_s3_candidates.py \
  --accepted-registry /path/to/ACCEPTED_S2/accepted_run_registry.csv \
  --config pure_deap_nsga/experiments/large_fluid_pairs/optimization_config_large_pairs.json \
  --output-dir /path/to/S3_FORMAL/S3_<UTC> \
  --top-k 5
```

正式 S3 要求 Git 工作树干净。输出中的 `s4_task_list.csv` 将每个入选候选展开为五个
独立 seed；S2 的 seed 42 只作为来源证据，不能替代 S4 的 seed 42 确认任务。未在 S2
出现的构型只记录为 `unobserved`，不得由其他构型结果推断排名。

S4 若有任务在冻结的 150 代达到上限但未满足 HV 连续窗口门，只允许选择这些任务做
例外扩展。先由 `prepare_s4_extension.py` 验证源批次、S3 lineage、终态 checkpoint
和全部哈希，再以同一配置、population、seed 和 archive tolerance 从 checkpoint 续算；
除 `maximum_generations` 单调增加外，优化器签名的任何变化都会被拒绝。扩展必须使用
新的 data root 和 run ID，不得覆盖正式 S4 原始目录。示例：

```bash
.venv/bin/python \
  pure_deap_nsga/experiments/large_fluid_pairs/prepare_s4_extension.py \
  --base-batch /path/to/BATCH_S4_<UTC> \
  --s3-task-list /path/to/S3/s4_task_list.csv \
  --config pure_deap_nsga/experiments/large_fluid_pairs/optimization_config_large_pairs.json \
  --output-dir /path/to/S4_EXTENSION/inputs \
  --target-maximum-generations 300

.venv/bin/python \
  pure_deap_nsga/experiments/large_fluid_pairs/run_large_scale.py \
  --config pure_deap_nsga/experiments/large_fluid_pairs/optimization_config_large_pairs.json \
  --data-root /path/to/S4_EXTENSION \
  --stage S4 --mode optimize \
  --task-list /path/to/S4_EXTENSION/inputs/s4_extension_task_list.csv \
  --population-size 100 --generations 300 --workers 8 --checkpoint-every 10
```
达到 300 代仍未满足 HV 门的少量任务使用 `S2_exception_extension`，保持 pop、seed、
HV 窗口和阈值不变，从新种群运行并允许最多 450 代；不得跨最大代数配置复用旧检查点。

### S4 canonical 验收与 S5 入口

S4 base 与 extension 不能直接拼接。`accept_s4_results.py` 以 S3 的 300 个任务键为全集，
保留已收敛 base run，并用 extension run 替换对应未收敛源 run。工具验证 manifest、
checkpoint、两次前沿复算、Pareto 和配置哈希，然后按固定边界重新计算 exact HV、样本
CV 和 exact IGD+。`S4_RECOMMENDABLE` 定义为三个稳定性门全部通过，并在同一 WP×seed
的 10 个候选中至少 4/5 次位于 top-3（边界并列全部保留）。正式执行要求 clean Git：

```bash
.venv/bin/python \
  pure_deap_nsga/experiments/large_fluid_pairs/accept_s4_results.py \
  --base-batch /path/to/S4_FORMAL/BATCH_S4_<UTC> \
  --extension-batch /path/to/S4_EXTENSION/BATCH_S4_<UTC> \
  --s3-task-list /path/to/S3_FORMAL/S3_<UTC>/s4_task_list.csv \
  --config pure_deap_nsga/experiments/large_fluid_pairs/optimization_config_large_pairs.json \
  --output-dir /path/to/S4_ACCEPTED/ACCEPTED_S4_<UTC>
```

S5 必须读取上述 acceptance，不能手工输入或静默换点。每个 WP 的效率、密度、折中点
都来自已有认证 Pareto 行；工具验证来源行、点哈希和完整 lineage。每点每次在新进程中
直接构造原始 CBSim 类，不读取优化器 cache，并保存能量闭合、火用状态恒等式及损失、
严格 pinch、状态/相态、HE 膨胀路径、压力、求解残差和 KPI 对照证据。正式批次固定至少
两次独立复算：

```bash
.venv/bin/python \
  pure_deap_nsga/experiments/large_fluid_pairs/run_s5_revalidation.py \
  --accepted-dir /path/to/S4_ACCEPTED/ACCEPTED_S4_<UTC> \
  --config pure_deap_nsga/experiments/large_fluid_pairs/optimization_config_large_pairs.json \
  --output-dir /path/to/S5_FORMAL/S5_<UTC> \
  --repeats 2 --timeout-s 120
```

`--allow-dirty --smoke-limit N` 只用于开发验证，manifest 状态为 `SMOKE_PASS`，不能作为
正式 S5 放行证据。

## 6. 数据契约

- `fluid_catalog.csv`：规范名、CoolProp 版本、Tc/Pc/Ttriple、GWP 来源、安全类、ODP、稳定性和法规。
- `pair_eligibility.csv`：WP、HP/HE、每道 gate、margin、压力范围、去留状态和原因码。
- `sampling_feasibility.parquet`：`run_id/wp/cfg/pair/sample_id/9 variables/feasible/failure_id/KPI`。
- `run_manifest.jsonl`：commit、dirty state、config SHA256、环境、seed、时间、评价数和状态。
- `fronts/{run_id}/{seed}/pareto.csv`、`generation_metrics.csv`、`seed_stability.csv`、`resource_usage.csv`。
- 失败 JSON 按 `failure_record.schema.json`；分析索引拆为 `failed_evaluations.csv`、`failure_issues.csv`、`solver_attempts.csv`。

### 6.1 求解失败阶段集合

`deepest_stage` 应优先保存最深根因，包装层异常只作 secondary code。

1. `CONFIG_FILTER`、`INPUT_DECODE`、`OPT_PRECHECK`、`PROPERTY_INPUT_BUILD`、`CB_CONSTRUCT`。
2. `HP_PRESSURE_SOLVE`、`HP_MASS_FLOW_SOLVE`、`HP_RECUPERATOR_SOLVE`、`HP_EFFICIENCY_OPT`、`HP_CONSISTENCY`。
3. `HE_PRESSURE_SOLVE`、`HE_MASS_FLOW_SOLVE`、`HE_RECUPERATOR_SOLVE`、`HE_EFFICIENCY_OPT`、`HE_CONSISTENCY`。
4. `CB_COUPLING_CONSISTENCY`、`KPI_SANITY`、`OBJECTIVE_EXTRACTION`、`RESULT_EXPORT`、`UNKNOWN_WRAPPER`。

根因码至少区分：配置/边界、CoolProp 物性域、求解器不收敛/残差/回退链、
换热 pinch、相态、压力、回热器约束、效率/守恒、KPI 异常和包装层异常。

### 6.2 失败参数最小集

- 身份：`run_id/evaluation_id/wp/cb_config/cb_class/fluid_hp/fluid_he`。
- 边界：`T_hs/T_cs`、储热温度/温差范围和所有固定 pinch/效率/压力参数快照。
- 九维设计变量：原始顺序、命名值、lb/ub、越界标志和距边界归一化距离。
- 求解器：方法名、`x0/bounds/options/x_final`、残差向量/L2/Linf/容差、
  `success/status/ier/message/nfev/njev/nit/elapsed_ms`和 fallback 父子关系。
- 热力学快照：失败前最后有效 HP/HE/冷热源/储热状态点，实际 pinch 与 margin、
  压比、Tc margin、干度、质量/能量平衡和失败的 PropsSI 输入对。
- 复现：commit/dirty state、config SHA256、CLI、seed/generation/individual index、Python/
  numpy/scipy/CoolProp/deap 版本、主机/进程、开始/结束时间和完整异常链 hash。

JSON 是权威记录；CSV 仅作关联索引：

- `failed_evaluations.csv`：一行一次评价，包九维值、根因、最终残差和 JSON 相对路径。
- `failure_issues.csv`：一行一个 issue，通过 `evaluation_id` 关联。
- `solver_attempts.csv`：一行一次求解/fallback 尝试，保存初末值、残差和迭代元数据。

## 7. 结论边界

只有同时通过 P0–P2、多 seed 收敛门和独立物理复算的工质对才可写为
“工程推荐”。探索池中的高 GWP、可燃或证据不完整工质只能用于机理对照。

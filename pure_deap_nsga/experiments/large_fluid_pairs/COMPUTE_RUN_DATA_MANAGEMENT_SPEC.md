# CBSim 计算轮次与数据管理规范 v1.0

## 1. 文档状态

| 字段 | 值 |
|---|---|
| 适用项目 | CBSim 数据中心卡诺电池多目标优化 |
| 基线分支 | `master` |
| 基线提交 | `be1b777e0ef2ff6deca85dc8a0fb2d5ac47773cf` |
| 状态 | 执行规范；其中标为“待实现”的能力不得视为当前 runner 已具备 |
| 数据范围 | P0/P1 工质预筛、S0–S5 仿真与优化、失败诊断、复算验收 |

本规范定义计算平台上的环境冻结、任务拆分、运行标识、目录结构、状态机、
数据契约、失败处理和轮次验收。目标是保证每个结果都能追溯到唯一代码、配置、
工况、构型、工质对、随机种子和运行环境，并避免并行任务或多 seed 相互覆盖。

## 2. 强制原则

1. **代码与数据分离**：仓库只保存代码、配置、Schema、轻量台账和汇总；原始运行数据存放在仓库外的数据根目录。
2. **一个任务一个目录**：最小优化任务为 `1 WP × 1 configuration × 1 fluid pair × 1 seed`。
3. **不可覆盖**：`run_id` 全局唯一；任何已进入终态的目录不得原位重跑。
4. **配置冻结**：每个任务保存实际使用的配置快照及 SHA-256，不只记录源路径。
5. **状态与物理解读分离**：`EMPTY` 表示本次搜索未找到可行前沿，不等于已证明热力学不可行。
6. **失败不自动重试**：失败任务先保留现场和诊断，再由人工决定是否生成新 `run_id` 重跑。
7. **原子发布**：输出先写临时文件，完成并校验后再原子重命名为正式文件。
8. **正式计算使用干净提交**：`git status --porcelain` 非空时不得进入 S1–S5 正式批次。

## 3. 计算开始前的环境门

在仓库根目录执行：

```bash
git checkout master
git pull --ff-only
git status --short
git rev-parse HEAD

uv venv .venv --python 3.11
uv sync --frozen
source .venv/bin/activate

python pure_deap_nsga/test_optimizer.py
python pure_deap_nsga/test_solver_diagnostics.py
python pure_deap_nsga/test_solver_diagnostics_acceptance.py
```

进入计算的强制条件：

- 优化器测试 `4/4 PASS`；
- 求解诊断测试 `6/6 PASS`；
- 诊断验收测试 `9/9 PASS`；
- Python 为 3.11，SciPy 为 `>=1.11.1,<1.12`；
- 配置文件可解析，CoolProp 中的全部工质名可识别；
- 正式 S1–S5 运行时工作树干净。

每台计算节点首次使用时还应做一组固定输入的单点复算，并与基准结果比较。
确定性输出要求数值一致；浮点环境存在合理差异时，应预先声明绝对/相对容差。

## 4. 轮次和最小任务

| 阶段 | 最小任务 | 主要输出 | 进入下一阶段的门 |
|---|---|---|---|
| P0 | 一个工质目录版本 | `fluid_catalog.csv` | 物性名和核心常数可查询 |
| P1 | 一个 WP × 全工质对 | `pair_eligibility.csv` | 各 gate 和原因码完整 |
| S0 | 一个 WP × 一个构型 × 一个工质对 × 固定设计点 | 单点结果和诊断 | 模型、物性和导出链可用 |
| S1 | 一个 WP × 一个构型 × 一个工质对 × 256 样本 | `sampling_feasibility.parquet` | 可行率与失败谱可解释 |
| S2 | 一个 WP × 一个构型 × 一个工质对 × seed 42 | 粗优化前沿 | 覆盖、HV 和可行率达门 |
| S3 | 一个 WP × 一个已验收构型的候选集合 | 候选排序、池化前沿和筛选依据 | 保留前 5 对并覆盖三个目标极值 |
| S4 | 一个 WP × 一个构型 × 一个工质对 × 一个 seed | 确认前沿 | 5-seed 稳定性达门 |
| S5 | 一个代表 Pareto 点 | 独立复算记录 | 能量、火用、相态守门通过 |

不得把多个 seed 写入同一任务目录。调度系统的 array job 可以批量生成任务，
但每个 array element 必须对应独立 `run_id` 和输出目录。

## 5. `run_id` 规范

格式：

```text
{stage}_{wp}_{cfg}_{fluid_hp}_{fluid_he}_seed{seed3}_{utc_timestamp}
```

示例：

```text
S2_DCB_SBVCHP-SBORC_R1233zdE_R134a_seed042_20260716T080000Z
```

规则：

- 仅使用 ASCII 字母、数字、连字符和下划线；
- 工质名中的括号和空格在 `run_id` 中移除，但 manifest 保留 CoolProp 规范名；
- 时间使用 UTC，格式为 `YYYYMMDDTHHMMSSZ`；
- P0/P1 或无随机种子的任务使用 `seedNA`；
- 重跑必须生成新时间戳，并在 manifest 中填写 `supersedes_run_id` 或 `retry_of_run_id`。

## 6. 数据根目录和任务目录

数据根目录必须位于仓库之外，例如：

```bash
export CBSIM_DATA_ROOT="$HOME/cbsim-runs"
```

规范目录：

```text
cbsim-runs/
├── run_registry.csv
└── S2_DCB_SBVCHP-SBORC_R1233zdE_R134a_seed042_20260716T080000Z/
    ├── config/
    │   ├── config.snapshot.json
    │   └── pair_selection.csv
    ├── metadata/
    │   ├── manifest.json
    │   ├── git_status.txt
    │   ├── python_packages.txt
    │   ├── host.json
    │   └── checksums.sha256
    ├── logs/
    │   ├── command.txt
    │   ├── stdout_stderr.log
    │   └── resource_usage.csv
    ├── outputs/
    │   ├── pareto.csv
    │   ├── generation_metrics.csv
    │   └── summary.json
    ├── failures/
    │   ├── records/
    │   │   └── evaluation_*.json
    │   ├── failed_evaluations.csv
    │   ├── failure_issues.csv
    │   └── solver_attempts.csv
    ├── checkpoints/
    └── status/
        └── COMPLETED
```

`RUNNING`、`COMPLETED` 等状态文件只能有一个。原始大文件不应直接提交 Git；
仓库中只提交经过审核的汇总表、Schema、说明和必要的小型验收 fixture。

## 7. Manifest 数据契约

每个任务开始前创建 `metadata/manifest.json`，至少包含：

```json
{
  "schema_version": "1.0",
  "run_id": "S2_DCB_SBVCHP-SBORC_R1233zdE_R134a_seed042_20260716T080000Z",
  "stage": "S2",
  "status": "RUNNING",
  "git_commit": "be1b777e0ef2ff6deca85dc8a0fb2d5ac47773cf",
  "git_dirty": false,
  "config_sha256": "...",
  "working_point": "DC-B",
  "configuration": "SBVCHP_SBORC",
  "fluid_hp": "R1233zd(E)",
  "fluid_he": "R134a",
  "algorithm": "NSGA2",
  "population_size": 48,
  "generations": 50,
  "seed": 42,
  "command": "...",
  "hostname": "...",
  "scheduler_job_id": null,
  "start_time_utc": "2026-07-16T08:00:00Z",
  "end_time_utc": null,
  "exit_code": null,
  "evaluation_count": null,
  "feasible_count": null,
  "pareto_size": null,
  "failure_count": null,
  "retry_of_run_id": null
}
```

终态写入时补齐结束时间、退出码、计数、结果路径及异常摘要。Manifest 更新也必须
采用临时文件加原子重命名，不得留下半写 JSON。

## 8. 状态机

正式实现应区分批次级 run 状态和最小任务级 case 状态，不能用一个 `status` 同时表示
整批与单个工质对的执行结果。

批次级状态：

```text
DRAFT -> PREFLIGHT -> READY -> QUEUED -> RUNNING <-> CHECKPOINTED
      -> COMPUTE_COMPLETE -> VALIDATING -> ACCEPTED
```

旁路终态为 `PREFLIGHT_BLOCKED`、`FAILED`、`CANCELLED`、`REJECTED`、`QUARANTINED`。

case 级状态：

```text
PLANNED -> {ELIGIBLE, FILTERED} -> QUEUED -> RUNNING
        -> {COMPLETED, EMPTY, FAILED_RETRYABLE, FAILED_FINAL, INTERRUPTED}
        -> {VALIDATED, REJECTED}
```

`FILTERED` 必须有 gate、margin 和 reason code；它不是缺失任务。批次只有在全部预期 case
进入允许终态、校验和与验收程序通过后才能 `ACCEPTED`。分析程序只读取 `ACCEPTED` 批次
中的 `VALIDATED` case。

简化的单任务执行状态可表示为：

```text
PLANNED -> RUNNING -> {COMPLETED, EMPTY, FAILED, TIMEOUT, CANCELLED}
                    -> CHECKPOINTED -> RUNNING
```

| 状态 | 定义 |
|---|---|
| `PLANNED` | 参数和目录已生成，进程尚未启动 |
| `RUNNING` | 进程存活，任务持有目录锁 |
| `CHECKPOINTED` | 有完整检查点，可用同一 run_id 恢复 |
| `COMPLETED` | 正常退出且输出通过完整性验收 |
| `EMPTY` | 正常退出但本次搜索未得到可行前沿 |
| `FAILED` | 异常退出或输出完整性验收失败 |
| `TIMEOUT` | 达到调度或硬超时限制 |
| `CANCELLED` | 人工或调度系统取消 |

终态不可返回 `RUNNING`。同一 run/case 只有 `CHECKPOINTED`、`INTERRUPTED` 或
`FAILED_RETRYABLE` 可以恢复，并且 code/config/schema/pair-list/environment 哈希必须一致；
否则创建新 `run_id/attempt_id`。发现已有目录锁时，新进程必须拒绝启动，不得共享目录写入。
状态迁移采用 append-only event，记录时间、执行者、原因和前后状态，不覆盖历史事件。

## 9. 日志、监控和检查点

每个任务必须记录：

- 完整命令、cwd、启动和结束时间；
- PID、hostname、调度任务号；
- CPU 时间、峰值 RSS、磁盘用量；
- 每代 `generation/n_evaluated/n_feasible/front_size/unique_ratio/HV`；
- 最近成功写入的 generation/checkpoint；
- stderr 异常摘要及完整日志路径。

监控至少覆盖：进程存活、硬超时、输出增长和资源异常。除硬超时外，不得因告警
自动杀死或自动重试任务。检查点内容至少包含种群、适应度、随机数状态、当前代数、
Hall of Fame/Pareto archive 和累计诊断计数。

## 10. 失败数据管理

失败 JSON 必须符合 `failure_record.schema.json`。权威记录为：

```text
failures/records/evaluation_{evaluation_id}.json
```

分析索引为：

- `failed_evaluations.csv`：一行一次失败评价；
- `failure_issues.csv`：一行一个根因或次级 issue；
- `solver_attempts.csv`：一行一次求解器或 fallback 尝试。

根因保存最深失败阶段，包装层错误仅作 secondary issue。至少保留九维变量及边界、
求解初末值、残差、迭代状态、最后有效热力学状态、失败 PropsSI 调用、异常链和复现环境。

当 `diagnostics_enabled=false` 或失败记录没有实际落盘时，不得启动正式 S1–S4 批次。

## 11. 输出完整性验收

### 11.1 所有任务

- manifest 可解析，`run_id` 与目录名一致；
- commit、配置哈希、命令和环境版本非空；
- 恰好存在一个终态文件；
- 输出临时文件全部消失；
- `checksums.sha256` 校验通过；
- 台账中 `run_id` 唯一；
- 计数满足 `evaluated = feasible + failed_or_infeasible`，或明确记录其他分类。
- 每个 penalty 评价恰好关联一个 evaluation outcome；失败至少关联一个 issue；
- solver 根因至少关联一个 solver attempt，三张失败索引不存在孤儿外键。

### 11.2 优化任务

- Pareto 表主键唯一，无 `NaN`、`inf` 和越界设计变量；
- `COMPLETED` 的 front 非空，`EMPTY` 的 front 为空且进程正常退出；
- 单运行末代可行率默认 `>=20%`，困难组合 `<20%` 标黄、`<5%` 阻断；
- 去重前沿至少 20 点，unique ratio `>=90%`；
- 末 20 代归一化 HV 相对改善 `<0.5%`。

### 11.3 多 seed

- seeds 固定为 `[17, 42, 73, 101, 202]`；
- 公共参考前沿下 HV 的 CV `<=5%`；
- 各 seed 到 union front 的归一化 IGD+ `<=0.03`；
- 三个极值 KPI 跨 seed CV `<=3%`；
- 推荐工质对/构型至少在 4/5 seeds 进入前列。

未过门时应记录为“未收敛/证据不足”，不得只保留表现最好的 seed。

## 12. 总台账

`run_registry.csv` 一行对应一个最小任务，字段至少为：

```text
run_id,stage,wp,cfg,fluid_hp,fluid_he,seed,commit,config_sha256,status,
start_utc,end_utc,elapsed_s,evaluations,feasible_count,pareto_size,
failure_count,result_path,manifest_path,retry_of_run_id
```

台账采用单写者或数据库事务更新。多个 worker 不得并发追加同一 CSV；可让 worker 写独立
manifest，批次结束后由汇总程序生成台账。

## 13. 当前 master 能力边界

截至基线提交，以下能力已存在：12×12 候选池、P0/P1 初步 CoolProp/Tc 预筛、NSGA-II
粗优化配置、求解诊断对象、失败记录 Schema 和验收 fixture。

以下能力尚未实现：输出目录和 run-id 参数、单工质对任务、pair-list、manifest、目录锁、
原子写、检查点/恢复、每代完整指标、失败 JSON/CSV 落盘、资源监控和自动台账。因此：

- P0/P1 初筛和单 worker 串行烟测可以执行；
- 不得在同一 clone 中并行运行当前 runner；
- 不得把当前 runner 直接用于 S1–S4 正式批次；
- 临时试运行结束后必须立即把 `results/` 和 `optimization.log` 复制到独立 run 目录。

正式计算放行条件见 `LARGE_FLUID_PAIR_IMPLEMENTATION_ROADMAP.md`。

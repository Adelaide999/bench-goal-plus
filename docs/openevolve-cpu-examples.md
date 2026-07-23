# OpenEvolve 无特殊硬件示例审计

## 结论

OpenEvolve 当前仓库确实有一批可作为**共同 task/evaluator substrate**、且不依赖 GPU/NPU、下载数据集、网络服务、编译器或外部可执行软件的示例。同一任务可以分别由原生 OpenEvolve、Plain Codex、Goal Plus + Codex 和 Goal Plus + Pi 四套独立 runner 执行，不需要把 Codex 接入 OpenEvolve 内部。

当前已经把 12 题固化为 `cpu_portable` task set，并实现批量 list、materialize、seed evaluator smoke、四路径 campaign prepare/run。主实验优先看 `background_blur` 与 `circle_packing_with_artifacts`；8 个 AlphaEvolve 几何/组合连续优化任务用于扩大题量；`function_minimization` 和 `k_module_problem` 主要作为接线与负对照。

**Docker 标记：不需要。** `cpu_portable` 12 题只使用 locked Python、
NumPy/SciPy；没有 Docker 的环境可以完整 materialize、evaluate 并启动四路径
campaign。这个结论不扩展到被排除的 OpenEvolve examples。

受管源码跟踪 [`ck0123/openevolve@bench-goal-plus`](https://github.com/ck0123/openevolve/tree/bench-goal-plus)；
`bootstrap` 只做 fast-forward，具体实验在 manifest 记录当次 resolved commit。
示例全集位于其 [`examples/`](https://github.com/ck0123/openevolve/tree/bench-goal-plus/examples)
目录。

## 已批量接入的 `cpu_portable` 任务

| 任务组 | task id | task 额外 Python 依赖 | Seed evaluator 实测 |
|---|---|---|---:|
| 接线/性能 | `function_minimization` | NumPy, SciPy | 0.018s |
| 接线/性能 | `background_blur` | NumPy | 9.070s |
| 连续几何 | `circle_packing_with_artifacts` | NumPy, SciPy | 0.202s |
| 负对照 | `k_module_problem` | 无 | 0.004s |
| AlphaEvolve 数学 | `alpha_circle_packing_rect` | NumPy | 0.008s |
| AlphaEvolve 数学 | `alpha_heilbronn_triangle` | NumPy | 0.007s |
| AlphaEvolve 数学 | `alpha_kissing_number` | NumPy | 0.006s |
| AlphaEvolve 数学 | `alpha_heilbronn_convex_13` | NumPy, SciPy | 0.009s |
| AlphaEvolve 数学 | `alpha_hexagon_packing_11` | NumPy | 0.012s |
| AlphaEvolve 数学 | `alpha_hexagon_packing_12` | NumPy | 0.013s |
| AlphaEvolve 数学 | `alpha_minimizing_max_min_dist_2` | NumPy, SciPy | 0.510s |
| AlphaEvolve 数学 | `alpha_minimizing_max_min_dist_3` | NumPy, SciPy | 0.486s |

12/12 seed 均通过 controller-owned evaluator，返回 finite `combined_score`；总 evaluator 时间 10.346s。12 × 4 共 48/48 方法单元也已成功批量 prepare；Goal Plus 两条路径都验证了 time zero 没有预建 `.gp` 状态。这里的“支持”严格指 task/evaluator/prompt/campaign ready；除 `function_minimization` 外，尚未宣称完成付费模型 E2E。

明确排除：`signal_processing` 的当前 primary metric contract 不成立；`claude_code_quickstart` 需要 Claude CLI；`attention_optimization` 需要 MLIR/编译器；ARC、SLDbench 和 symbolic regression 需要外部数据；TSP 需要 C++/Torch；JAX/Optax 数学任务虽可用 CPU，但不符合本批“无额外环境”的筛选条件。

---

## OpenEvolve 的真实预算语义

- `max_iterations=N` 表示初始程序评测之外，再提交最多 N 个 evolutionary offspring；不是 N 个相互独立完整 agent。
- `evaluator.parallel_evaluations=K` 同时控制 process worker 数；每个 worker 会采样 parent/inspirations、调用模型并执行 evaluator。
- controller 初次可提交最多约 `2K` 个 futures；它们在提交时读取 database snapshot，排队任务可能看不到刚完成的新 evidence。
- `database.num_islands` 是 population diversity 结构，不是实际 CPU 并发数。
- evaluator 需要返回 higher-is-better 的 `combined_score`；原始 lower-is-better metric 通常在 adapter 中变换。
- 一次 iteration 可能因 retry、novelty regeneration 或失败重试产生多次模型请求，因此公平预算必须记录实际 calls。
- 当前 OpenAI-compatible client 只返回文本，没有持久化 API response usage；无法直接得到完整 token/cost ledger，这是正式成本对比前的 instrumentation gap，但不影响复用 tasks。
- 当前模型后端只有 OpenAI-compatible API 和 Claude Code CLI，没有 Codex CLI provider；**本计划不需要增加 Codex provider**，因为 Codex-only 与 Goal Plus 是 OpenEvolve 之外的独立 runner。

因此，`Goal Plus 20 verifier calls` 不能机械对应 `OpenEvolve --iterations 20`：后者还包含一次 initial evaluation，并可能有额外模型请求或 cascade 子评测。

---

## 候选分级

| 级别 | 示例 | 默认规模 | 依赖/摩擦 | 价值判断 |
|---|---|---:|---|---|
| A | `background_blur` | 100 iterations，评测需串行 | NumPy；无数据下载 | 最好的系统优化主实验；报告 62× seed、2.6× expert，且有反作弊测试 |
| A | `circle_packing_with_artifacts` | 500 iterations、4 workers | NumPy/SciPy；novelty embedding 可关闭 | 与 Swarm circle packing 重合，连续 score + artifacts，直接打 OpenEvolve |
| A | 8 个 `alpha_*` portable tasks | 50–200 iterations | NumPy/SciPy | 已批量接入；连续几何/组合 score，适合扩充 campaign |
| B | `signal_processing` | 100 iterations | NumPy/SciPy/sklearn 等 | 有连续梯度，但缺 canonical `combined_score`，先不进严格主结果 |
| B | `function_minimization` | 10 iterations、3 workers | SciPy | 很快但偏 toy，只做 adapter/ledger smoke |
| 暂缓 | `third_autocorr_ineq` / `erdos_min_overlap` | 200 iterations | NumPy + JAX/Optax CPU | 目标值有价值，但不进入本轮零额外环境 batch |
| B | `sldbench` | 7 核心任务，各 50 iterations | Hugging Face dataset、SciPy | 与 agentic scaling 高度相关，CPU 可跑；数据下载后值得作为第二批 |
| B | `tsp_tour_minimization` | 128×1000-city instances | C++17、NumPy/Torch；单候选可到分钟级 | 无 GPU 要求但 evaluator 很重，适合 Linux 后续 |
| B | `algotune` | 8 个 CPU 数值任务；README 全套约 200 分钟 | 依赖非常重，timing 与 BLAS/JAX/CPU 相关 | 有 expert/速度对比，但先固定容器和 CPU 才能用 |
| C | `k_module_problem` | 50 iterations、4 workers | 纯 Python | 只做负对照：本质是 625 组合与 pass@k，不能支撑主 claim |
| C | `arc_benchmark` | pass@2 | Kaggle 数据、API 配置 | 正是要避免的二元 sampling 叙事 |
| C | `rust_adaptive_sort` / `r_robust_regression` | 100–150 iterations | Rust 或 R toolchain | 不依赖特殊硬件，但没有第一批任务必要 |
| 暂缓 | `attention_optimization` | 50 | MLIR/LLVM 工具链 | 特殊软件环境 |
| 暂缓 | `mlx_metal_kernel_opt` | hardware timing | Apple Silicon/MLX | 当前 Intel Mac 不匹配 |
| 暂缓 | `online_judge_programming` | 外部提交 | Kattis credential/network | evaluator 不是离线自包含 |
| 暂缓 | `llm_prompt_optimization` / `web_scraper_optillm` / `lm_eval` | 额外模型或网络 | 二次 LLM、proxy、模型/数据下载 | 会把 search 方法与 evaluator 模型/网络混在一起 |

### 本机 evaluator-only 复核

- `k_module_problem` 的核心 `evaluate()` 在约毫秒级返回 seed `0/4`，但 standalone `__main__` 固定读取 `result["metrics"]`，与成功路径的扁平返回不一致，会触发 `KeyError`。通用 adapter 直接加载 `evaluate()`，无需修改 upstream 即可避开损坏的打印入口。
- `third_autocorr_ineq` 和 `erdos_min_overlap` 在当前基础 Python 环境缺 JAX；这是普通 CPU 依赖，不是特殊硬件要求。
- `circle_packing_rect` evaluator 可载入，但 seed 当前得到 0 分；接线时必须先确认这是预期弱 seed，而非运行环境错误。
- `background_blur` 只需 NumPy 作为 task 依赖，但要先安装 OpenEvolve 自身依赖；其文档明确要求 `parallel_evaluations: 1`，否则 CPU 争用会污染 timing fitness。

---

## 建议的 OpenEvolve 对照包

### 第一阶段：三题最小方法比较

| 任务 | 代表能力 | Pilot 预算 |
|---|---|---:|
| Function Minimization | harness/ledger 是否正确 | 10 calls |
| Background Blur | correctness gate 下的真实性能搜索 | 20 calls，正式再扩到 100 |
| Circle Packing with Artifacts | 数学大空间、多 lineage/种群 | 20 calls，正式 100–500 |

### 第二阶段：十二题批量 campaign

在三题 pilot 稳定后，直接展开整个 `cpu_portable` set，而不是逐题手工接线。12 题都满足单文件 seed、`EVOLVE-BLOCK`、`evaluate(program_path)` 和明确 `combined_score`，同时覆盖：

- 性能优化与 correctness gate；
- 连续几何与组合搜索；
- 弱 seed、稀疏 score 与可归因反馈；
- OpenEvolve 原生 population/artifact 优势。

`signal_processing`、JAX/Optax 数学题和外部数据任务放到以后：前者 metric contract 有问题，后两类违反当前无额外环境的筛选条件。

每题运行 Plain Codex、原生 OpenEvolve、Goal Plus + Codex 和 Goal Plus + Pi，固定 `T`、`K`、模型与 seed，正式结果至少 3 seeds。这样 Goal Plus 若获胜，较难解释成单纯 Pass@K。

---

## 四套 runner 复用同一任务是否好改

结论是：**已用一个通用 adapter 批量接通 12 题，但不追求自动兼容 OpenEvolve 的全部 examples。** 当前 `cpu_portable` 任务都具备相同的基本结构：

- 单文件 `initial_program.py`；
- `EVOLVE-BLOCK-START/END` 定义允许修改的区域；
- `config.yaml` 中有可提取的 `prompt.system_message`；
- evaluator 暴露同步的 `evaluate(program_path)`；
- 返回 `dict` 或 `EvaluationResult(metrics, artifacts)`，且都有 higher-is-better `combined_score`。

因此只需要一个通用 `openevolve_task` adapter，加上每题一份很薄的 manifest，而不是为每题重写 runner：

```text
TaskSpec
├── seed_path / artifact_name / editable_region
├── prompt_from_config
├── evaluator_module / working_dir / timeout / resource_lock
├── primary_metric / direction / validity_metric
└── requirements / environment_digest

materialize(task_id) → isolated workspace
evaluate(task_id, artifact) → controller-owned subprocess → canonical JSON
```

统一结果只包装返回类型，不替换 raw metrics：

```json
{
  "valid": true,
  "primary_metric": {"name": "combined_score", "value": 0.91, "direction": "maximize"},
  "raw_metrics": {},
  "artifacts": {},
  "elapsed_seconds": 1.23
}
```

### 四套独立入口

| 方法 | 如何消费同一 TaskSpec | 是否修改 OpenEvolve 搜索器 |
|---|---|---|
| 原生 OpenEvolve | 继续运行原生 `openevolve-run seed evaluator --config ...`；必要时 evaluator 文件只是调用统一 controller 的薄代理 | 否 |
| Plain Codex | `scripts/run_codex.py` materialize workspace；给 Codex task prompt 和受预算约束的 `evaluate` 命令 | 否 |
| Goal Plus + Codex/Pi | 多条 lineage 共享 Search Evidence/Schema，但 materialize 与 `evaluate` 完全复用上面同一入口 | 否 |

OpenEvolve 保持自己的 population、islands、prompt sampler 和模型 API；Codex-only/Goal Plus 不经过 OpenEvolve controller。三者共享的只有 seed、允许编辑面、依赖环境、evaluator、metric 和预算 ticket。

### 任务兼容性分层

| 任务 | 统一入口难度 | 需要的 task-specific 处理 | 结论 |
|---|---:|---|---|
| `function_minimization` | 低 | manifest + `EvaluationResult` 归一化 | 先做接线 smoke |
| `background_blur` | 低 | evaluator 强制 `E=1`，记录 CPU 指纹 | 适合首批主实验 |
| `circle_packing_with_artifacts` | 低 | 保留 artifacts/validity；固定依赖 | 适合首批主实验 |
| 8 个 `alpha_*` portable tasks | 低 | manifest 声明 NumPy/SciPy；保留 raw metrics | 已批量接入 |
| `third_autocorr_ineq` / `erdos_min_overlap` | 低到中 | JAX/Optax CPU 环境与较长 timeout | 本批暂缓 |
| `signal_processing` | 中 | 先冻结 canonical score；不能沿用 OpenEvolve 的数值 metric 平均 fallback | 第二批，暂不作为严格结果 |
| `k_module_problem` | 低 | wrapper 直接调用 `evaluate()`，绕过损坏的 standalone 打印入口 | 只做负对照 |
| AlgoTune / SLDbench / TSP | 中到高 | 多任务生成、数据集或重型 toolchain；每族另写 adapter | 暂缓，不纳入首个统一包 |
| prompt/network/hardware examples | 高或目标混杂 | 二次 LLM、外部服务、凭据或特定硬件 | 直接排除 |

### 仍需单独处理的公平性问题

复用任务并不自动保证搜索策略对比完全公平。原生 OpenEvolve 仍需在外围记录 evaluator tickets、wall time 和可得到的 API usage；Plain Codex 与 Goal Plus 记录 Codex usage。若三者模型/provider 不同，结果只能称为**系统级 baseline**，不能单独归因于搜索策略。这个问题通过实验分层和报告解决，不需要把 Codex 嵌进 OpenEvolve。

第一版已经落地：`tasks.json` 固化 task set，adapter 提供 materialize/evaluate，`openevolve_task.py` 提供批量 seed smoke，comparison harness 提供 task × method campaign prepare/run。仍然不做全 examples 自动发现，也不改 OpenEvolve provider。

---

## 最值得利用的两个 OpenEvolve 反例

1. **K-Module**：OpenEvolve 自己的结果显示 rich attribution feedback 能让 iterative refinement 约 3 轮解决，而 population 平均约 52.3 iterations。它提醒我们：有结构化、可归因 evidence 时，Goal Plus 应该比盲目 population 更快；但这题只能做机制诊断，不能当主 benchmark。
2. **Background Blur**：OpenEvolve 报告 62× 相对故意写慢的 seed，但只有 2.6× 相对 competent expert。Goal Plus 的结果也必须同时对 seed、expert 和质量门禁报告，防止靠挑弱 baseline 讲故事。

这两个例子正好规定了实验叙事：并发不是目标，**并发条件下更少重复、更快形成可归因知识、在同样工作量下找到更好的 artifact** 才是目标。

---

## 2026-07-22 首个 Plain Codex 闭环

已在 `bench-goal-plus` 实现第一版 `openevolve_task` 通用适配器，并用 `function_minimization` 完成真实闭环。适配器没有修改 OpenEvolve provider 或搜索器，而是直接复用当次 branch snapshot 的 `Config`、`Evaluator`、`EVOLVE-BLOCK` 和 raw metrics：

```text
tasks.json -> materialize isolated workspace -> public evaluator tickets
           -> Plain Codex edits candidate.py -> reserved final evaluation -> archive
```

| 项目 | 实测结果 |
|---|---:|
| OpenEvolve commit | `411fb59c886c18704caaffb611e17cf9e7d824d2` |
| Seed `combined_score` | 1.2147685971 |
| Final `combined_score` | 1.4997641484 |
| 相对提升 | 23.46% |
| Evaluator calls | 4 public + 1 final |
| Codex wall time | 110.44 s |
| Codex usage | 200,450 input（169,472 cached）/ 3,280 output / 858 reasoning |

最终候选通过 OpenEvolve evaluator 的 10/10 trials，`distance_score=1.0`、`reliability_score=1.0`。完整候选、原始 metrics、调用轨迹和 Codex JSONL 见 [run summary](../evidence/runs/2026-07-22-openevolve-function-minimization-plain-codex/summary.json)。

这个结果只把“同一 OpenEvolve task/evaluator 可供 Plain Codex 消费”从设计变成了实证。它还不能用于宣称优于 OpenEvolve：本次没有跑 matched native search，Function Minimization 偏 toy，而且 Codex 默认模型身份没有被 CLI 证据显式记录。下一步是在相同 ticket budget 下补原生 OpenEvolve，然后把同一 adapter 交给 Goal Plus。

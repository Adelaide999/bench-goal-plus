# OpenEvolve 无特殊硬件示例审计

## 结论

OpenEvolve 当前仓库确实有一批可作为**共同 task/evaluator substrate**、且不依赖 GPU/特殊硬件的示例。同一任务可以分别由原生 OpenEvolve、Plain Codex 和 Goal Plus 三套独立 runner 执行，不需要把 Codex 接入 OpenEvolve 内部。最值得先跑的不是 ARC 或 K-Module 这类 Pass@k toy，而是：

1. `background_blur`：真实性能优化、硬质量门禁、专家 baseline；
2. `circle_packing_with_artifacts`：连续数学优化、丰富失败反馈、现成 OpenEvolve 强基线；
3. `third_autocorr_ineq` / `erdos_min_overlap`：与 Swarm/AlphaEvolve 重合，可复用论文目标值；
4. `function_minimization`：只作为 10-iteration 快速接线 smoke；
5. `signal_processing`：连续多目标科学优化，但 metric contract 要先修正，放第二批。

源代码固定为 [`algorithmicsuperintelligence/openevolve@411fb59`](https://github.com/algorithmicsuperintelligence/openevolve/tree/411fb59c886c18704caaffb611e17cf9e7d824d2)；本次用 `git ls-remote` 确认该提交仍是 upstream HEAD。示例全集位于其 [`examples/`](https://github.com/algorithmicsuperintelligence/openevolve/tree/411fb59c886c18704caaffb611e17cf9e7d824d2/examples) 目录。

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
| A | `third_autocorr_ineq` | 200 iterations | NumPy + JAX CPU | 与 Swarm/AlphaEvolve 重合，目标常数可复用 |
| A | `erdos_min_overlap` | 200 iterations | NumPy + JAX CPU | 同上，适合验证数学策略迁移 |
| B | `signal_processing` | 100 iterations | NumPy/SciPy/sklearn 等 | 有连续梯度，但缺 canonical `combined_score`，先不进严格主结果 |
| B | `function_minimization` | 10 iterations、3 workers | SciPy | 很快但偏 toy，只做 adapter/ledger smoke |
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

- `k_module_problem` 的核心 `evaluate()` 在约毫秒级返回 seed `0/4`，但 standalone `__main__` 固定读取 `result["metrics"]`，与成功路径的扁平返回不一致，会触发 `KeyError`。它需要小修后才能作为 smoke。
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

### 第二阶段：四题严格主实验

在上述后两题基础上加入 `third_autocorr_ineq`、`erdos_min_overlap`。这四题都满足单文件 seed、`EVOLVE-BLOCK`、`evaluate(program_path)` 和明确 `combined_score`，同时覆盖：

- 性能优化与 correctness gate；
- 连续几何搜索；
- 理论数学目标；
- OpenEvolve 原生 population/artifact 优势。

`signal_processing` 放到第二批：它虽能共用入口，但 evaluator 没有返回 OpenEvolve 首选的 `combined_score`，原生 OpenEvolve 会退化为对所有数值 metric 求平均，其中混有需要最小化的 penalty。除非先冻结一个对三种方法完全相同的 canonical score，否则不适合作为严格主结果。

每题运行 Plain Codex、Independent-4、原生 OpenEvolve、Goal Plus-4，至少 3 seeds。这样 Goal Plus 若获胜，较难解释成单纯 Pass@4。

---

## 三套 runner 复用同一任务是否好改

结论是：**第一批很好改，但不要追求自动兼容 OpenEvolve 的全部 examples。** 当前建议的 Function Minimization、Background Blur、Circle Packing with Artifacts、Third Autocorrelation 和 Erdős Minimum Overlap 都已经具备相同的基本结构：

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

### 三套独立入口

| 方法 | 如何消费同一 TaskSpec | 是否修改 OpenEvolve 搜索器 |
|---|---|---|
| 原生 OpenEvolve | 继续运行原生 `openevolve-run seed evaluator --config ...`；必要时 evaluator 文件只是调用统一 controller 的薄代理 | 否 |
| Plain Codex | `scripts/run_codex.py` materialize workspace；给 Codex task prompt 和受预算约束的 `evaluate` 命令 | 否 |
| Goal Plus | 多条 Codex lane 共享 Search Evidence/Schema，但 materialize 与 `evaluate` 完全复用上面同一入口 | 否 |

OpenEvolve 保持自己的 population、islands、prompt sampler 和模型 API；Codex-only/Goal Plus 不经过 OpenEvolve controller。三者共享的只有 seed、允许编辑面、依赖环境、evaluator、metric 和预算 ticket。

### 任务兼容性分层

| 任务 | 统一入口难度 | 需要的 task-specific 处理 | 结论 |
|---|---:|---|---|
| `function_minimization` | 低 | manifest + `EvaluationResult` 归一化 | 先做接线 smoke |
| `background_blur` | 低 | evaluator 强制 `E=1`，记录 CPU 指纹 | 适合首批主实验 |
| `circle_packing_with_artifacts` | 低 | 保留 artifacts/validity；固定依赖 | 适合首批主实验 |
| `third_autocorr_ineq` | 低到中 | JAX/Optax CPU 环境与较长 timeout | 环境固定后可直接接 |
| `erdos_min_overlap` | 低到中 | JAX/Optax CPU 环境与较长 timeout | 环境固定后可直接接 |
| `signal_processing` | 中 | 先冻结 canonical score；不能沿用 OpenEvolve 的数值 metric 平均 fallback | 第二批，暂不作为严格结果 |
| `k_module_problem` | 低 | wrapper 直接调用 `evaluate()`，绕过损坏的 standalone 打印入口 | 只做负对照 |
| AlgoTune / SLDbench / TSP | 中到高 | 多任务生成、数据集或重型 toolchain；每族另写 adapter | 暂缓，不纳入首个统一包 |
| prompt/network/hardware examples | 高或目标混杂 | 二次 LLM、外部服务、凭据或特定硬件 | 直接排除 |

### 仍需单独处理的公平性问题

复用任务并不自动保证搜索策略对比完全公平。原生 OpenEvolve 仍需在外围记录 evaluator tickets、wall time 和可得到的 API usage；Plain Codex 与 Goal Plus 记录 Codex usage。若三者模型/provider 不同，结果只能称为**系统级 baseline**，不能单独归因于搜索策略。这个问题通过实验分层和报告解决，不需要把 Codex 嵌进 OpenEvolve。

第一版实现量可控：通用 TaskSpec/materialize/evaluate wrapper 约 1 天，接通 Function Minimization + Background Blur + Circle Packing 约 1–2 天；JAX 两题主要是锁环境与测 timeout。首批不做全 examples 自动发现，也不碰 OpenEvolve provider。

---

## 最值得利用的两个 OpenEvolve 反例

1. **K-Module**：OpenEvolve 自己的结果显示 rich attribution feedback 能让 iterative refinement 约 3 轮解决，而 population 平均约 52.3 iterations。它提醒我们：有结构化、可归因 evidence 时，Goal Plus 应该比盲目 population 更快；但这题只能做机制诊断，不能当主 benchmark。
2. **Background Blur**：OpenEvolve 报告 62× 相对故意写慢的 seed，但只有 2.6× 相对 competent expert。Goal Plus 的结果也必须同时对 seed、expert 和质量门禁报告，防止靠挑弱 baseline 讲故事。

这两个例子正好规定了实验叙事：并发不是目标，**并发条件下更少重复、更快形成可归因知识、在同样工作量下找到更好的 artifact** 才是目标。

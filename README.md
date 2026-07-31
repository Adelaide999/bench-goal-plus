# bench-goal-plus

Goal Plus 的 benchmark 集成与实验控制仓。它把此前散落在 `mythink/agentic-scaling/benchmark-smoke`、各上游 checkout 和研究计划里的状态，收敛成可验证、可逐项推进的工程项目。

**基于 attitude 的 agent 预分析认为：核心关注，必须系统化推进——真正要证明的不是“Codex 能打开这些仓库”，而是同一任务、同一 evaluator、同一预算下，plain Codex 与 Goal Plus + Codex 的搜索轨迹和 best-seen 提升可以复现、计费并公平比较。**

## 先分清实验对象

本仓同时追踪方法和任务，但不会把它们混成“benchmark 数量”：

| 层次 | 当前对象 | 作用 |
|---|---|---|
| Agent / 搜索方案 | Plain Codex、Independent Parallel、Goal Plus、OpenEvolve、EvoX、AdaEvolve、Swarm、AB-MCTS | 决定如何产生、共享、选择和延续候选 |
| Agent host / runtime | Codex CLI、Pi、Goal Plus runtime、SkyDiscover、OpenEvolve runtime、SForge | 启动模型、workspace、进程和 benchmark-native harness |
| 正式 Benchmark | ALE-Bench、HeuriGym、Frontier-Engineering、AutoLab、Frontier-CS、EdgeBench、PERFOPT-Bench | 提供任务、artifact、evaluator 和 raw metric |
| 实验 substrate / task pack | SwarmResearch 15 题、OpenEvolve CPU examples、SkyDiscover Circle Packing、Local VLIW replica | 复用任务做论文对标、方法 pilot 或接线诊断 |

因此，**EvoX / AdaEvolve 是方法，SkyDiscover 是承载它们的 runtime，不是
benchmark**。
OpenEvolve 同样是方法及参考 runtime；它仓库里的 examples 可作为任务包，但不
自动变成一套正式 benchmark。完整边界见
[实验对象分类](docs/experiment-taxonomy.md)，本机哪些正式 benchmark case
可以直接跑见
[Benchmark 本机运行能力](docs/benchmarks/README.md#本机可直接运行什么)。

## 当前结果

- 已跟踪 10 个 GitHub fork；EdgeBench fork 也已纳入统一版本清单。
- 11 个受管源码/runtime checkout 已全部收敛到 ignored `third_party/`；每个仓只跟踪明确的 fork branch，`bootstrap` 自动 fast-forward，具体实验则在 run manifest 冻结当次 commit。EdgeBench 可单独执行 `bootstrap --only edgebench`，其 SForge/Goal Plus branch、任务 revision、Codex auth policy 和单题镜像由同一 control plane 检查。
- PERFOPT-Bench 当前没有可 fork 的公开可执行 GitHub 仓库，只有 4open.science artifact 与宣传站，因此明确标为 `blocked`，不拿网站仓冒充 benchmark。
- ALE-Bench Lite、HeuriGym、AutoLab 已有本机官方 verifier / 远端模型 smoke 证据。
- ALE-Bench Lite `ahc027` 已完成首个真实 plain Codex smoke：`gpt-5.4-mini` 改写候选后 5/5 public-lite cases accepted，raw score 从 61,302,533 降到 55,181,186（该题越低越好，改善 9.99%）。
- OpenEvolve `function_minimization` 已通过通用 task adapter 完成 Plain Codex 闭环：复用原生 evaluator，`combined_score` 从 1.2147685971 提升到 1.4997641484（+23.46%），共 4 public + 1 final calls；这是接线 smoke，不是 matched OpenEvolve baseline。
- OpenEvolve 已筛出并批量接入 12 个 `cpu_portable` tasks：只使用标准库/NumPy/SciPy，不需要 GPU、NPU、下载数据集、网络服务、编译器或额外可执行软件。12/12 seed 通过官方 evaluator（合计 evaluator 时间 10.35s），12 × 4 共 48/48 方法单元也已批量 prepare；这 11 个新增任务当前是 evaluator/prompt/campaign ready，尚未冒充已完成真实模型 E2E。
- OpenEvolve `function_minimization` 已完成 [四路径首轮 smoke](evidence/runs/2026-07-22-openevolve-four-path-5m-summary.md)：统一 `gpt-5.6-luna/high`、`T=300s`、`K=2`。该轮保留 native OpenEvolve / plain Codex 结果，并暴露出 Goal Plus 仅靠 controller closeout 也可能误报完成的问题。
- Goal Plus + Codex/Pi 曾通过 [controller-prepared 严格重跑](evidence/runs/2026-07-22-goal-plus-codex-pi-strict-rerun.md) 验证底层 worker、verifier 和 promotion 能力；该入口现保留为历史诊断证据，不再作为标准主实验。标准入口改为 Plain Codex 使用 common task prompt，Codex + Goal Plus 只增加 `/goal-plus` 前缀和完整配置后缀，并让 Goal/Spec/Run 全部在计时后的自然流程中创建。
- Goal Plus + Codex 已完成 [自然 prompt 标准入口 E2E](evidence/runs/2026-07-22-goal-plus-codex-natural-prompt.md)：prepare 后不存在 `.gp/`，定时运行内自然创建 Goal/Spec/Run 和两个 Codex workers；`gpt-5.6-sol/high`、`T=300s`、`K=2` 下，`combined_score` 从 1.119176 提升到 1.499540（+33.99%），两个 worker 都提交 verifier 结果并完成 promotion/report。
- HeuriGym `operator_scheduling` 已完成 [Plain Codex / Goal Plus + Codex 首轮真实 E2E](evidence/runs/2026-07-22-heurigym-operator-scheduling-codex-goal-plus.md)：两者共享 `gpt-5.6-sol/high`、`T=300s`、`K=2`、common prompt 和官方五-case evaluator；seed `total_cost=138`，Plain Codex 得 62，Goal Plus + Codex 得 95。它是接线证据，不是单次方法排名。
- Standalone benchmark 已收敛到同一 [Plain Codex / Goal Plus + Codex runner](experiments/benchmark_compare/README.md)：当前支持 ALE-Bench Lite `ahc027`、AutoLab `toy_isa_opt`、Frontier-Engineering `MallocLab`、Frontier-CS `problem-0`、HeuriGym `operator_scheduling`，以及明确标为非官方结果的 host-only `local-vliw`；每题仍保留自己的 artifact、evaluator、raw metric、方向、timeout 和资源要求。
- AutoLab host-portable smoke 已跑通：`gpt-5.6-sol/high`、`K=2` 下 Plain Codex 在 `T=240s` 从 `9220` 降到 `1547 cycles`；Goal Plus 在 `T=360s` 创建 2 个已绑定 Codex lineage，至少 1 个 worker 提交 verifier，但最终仍为 seed `9220`。这证明路径成立，不代表 Goal Plus 输赢。
- Frontier-Engineering MallocLab 的上游 evaluator 已在 macOS 通过 portable rebuild：seed `28/100`；Plain Codex `T=300s,K=2` 达到 `90/100`，Goal Plus `T=420s,K=2` 的 best verified/promoted 结果为 `89/100`。两者都通过 `11/11` traces；预算不同，仍只是各自接线 smoke。
- ALE-Bench Lite `ahc027` 的通用 Goal Plus 入口也已完成真实 E2E：`gpt-5.6-sol/high`、`T=480s`、`K=2` 下创建 2 个已绑定且均提交 verifier 的 Codex lineage，9 次 process-verifier iteration 后从 seed `55,181,186` 降到最终 `52,693,209`（越低越好，改善 `4.51%`）；本轮共记录 12 次 evaluator command/call，仍是接线证据而非 matched 方法排名。
- Frontier-CS problem 0 已完成 Docker host-capable 的两条真实路径：Plain Codex `T=180s,K=2` 最终 `93.4561753`（12 calls）；Goal Plus `T=420s,K=2` 创建 2 个已绑定、均有 verifier 的 lineage，7 次 process iterations 后 search best `93.3980341`、promotion gate `93.2217282`、独立 final `93.3097979`（10 calls）。该上游使用 clock-seeded 搜索，三次分数差异是已知噪声，不能把这轮当作方法排名。
- SkyDiscover runtime + EvoX 方法已完成 DeepSeek OpenAI-compatible 的
  Circle Packing 1-iteration smoke；这是 method/task compatibility 证据，
  不是新增 benchmark，也不是论文可比实验。
- SkyDiscover Best-of-N 已通过本仓统一控制面跑通
  [`function_minimization` 1-iteration 功能 smoke](evidence/runs/2026-07-24-skydiscover-best-of-n-function-minimization-smoke.json)：
  `gpt-5.6-luna/medium`、`K=1`，35.38 秒内从 `1.4286455109`
  提升到 controller final `1.4995399520`。candidate workspace bridge、
  checkpoint、精确 evaluator ledger 和独立 final evaluation 均已接通；
  native seed/best-test 仍在计时内且 usage/实际并发遥测缺失，因此 registry
  只提升为 `benchmark_adapter=partial`。
- SkyDiscover EvoX 已完成
  [`function_minimization` 真实 1-iteration smoke](evidence/runs/2026-07-24-skydiscover-evox-function-minimization-smoke.json)：
  `glm-5.2/medium`、`T=300s`、`K=1`，75.54 秒内执行 strategy
  meta-evolution、自动生成 variation operators，并在一次无效候选重试后将
  `combined_score` 从 `1.4286455109` 提升到 `1.4995399684`，共 6 次
  evaluator calls。
- SkyDiscover AdaEvolve 已完成
  [`function_minimization` 真实 1-iteration smoke](evidence/runs/2026-07-24-skydiscover-adaevolve-function-minimization-smoke.json)：
  `glm-5.2/medium`、`T=240s`、`K=1`，31.55 秒内运行双 island、自适应/UCB
  选择和 checkpoint；生成候选有效但仅得 `0.5010882153`，所以原生 selector
  正确保留 `1.4286455109` 的 seed。该结果证明执行与选择链路，不代表优化质量。
- 已在当前 Mac 为可执行 benchmark 建立代表 case 的环境证据：HeuriGym、
  Frontier-Engineering MallocLab、AutoLab Toy ISA 使用 host 环境；ALE、
  Frontier-CS、EdgeBench 使用 Docker 正式评分路径；SwarmResearch 当前只有
  Docker evaluator 证据。完整空间表见
  [镜像空间与 Linux 规划](docs/docker-storage-plan.md)。
- 已建立 [Benchmark 快速导读](docs/benchmarks/README.md)：记录当前可跑题数、coverage/campaign 时间，并为 7 套 active benchmark 展开一个真实 case 的输入、agent 动作、期望输出和 verifier。
- Docker 已成为 registry 一等字段：`scripts/status.py` 直接显示
  `REQUIRED / NO / MIXED / N/A`；[Docker 依赖速查](docs/benchmarks/README.md#docker-依赖速查)
  明确没有 Docker 时仍可运行的 task 与不能替代的官方评分边界。
- 已建立 [Goal Plus 接入与并发实验协议](docs/goal-plus-benchmark-experiment.md)：区分 agent/evaluator/task 三层并发，定义 matched-budget baseline、逐 benchmark 整改和非 Pass@K 的验收门槛；OpenEvolve 自带 CPU 任务见 [示例审计](docs/openevolve-cpu-examples.md)。
- 已建立 [可移植复现环境](docs/reproducible-environment.md)：固定 Python 依赖、跟踪 OpenEvolve/Goal Plus fork branch，自动 bootstrap/doctor，并在每个 run manifest 记录实际 commit；四条独立路径各自生成隔离实验目录。Goal Plus 的 `.gp` 只存在于临时 task workspace。
- OpenEvolve example 的自然 `/goal-plus` 标准入口已成为统一模板；ALE-Bench Lite、HeuriGym、AutoLab、Frontier-Engineering 和 Frontier-CS 现在复用同一 common-prompt / Goal Plus-suffix 结构。
- EdgeBench 已接入 campaign controller：跟踪 fork branch、固定 HuggingFace revision，按 profile 精确拉取任务/镜像，区分 Plain Codex 的 K 个独立 replica 与 Goal Plus 的 K 个 internal workers，并提供 `prepare / run / status / stop / finalize`。VLIW 已完成同模型、同 `T/K` 的真实 lifecycle E2E，judge lifecycle、evaluator calls 和 Codex session usage 均可回收；`T=120s` 尚不足以 dispatch Goal Plus worker，所以它仍不是方法效果对比。
- 原先位于 Goal Plus `examples-hide/vliw_kernel_optimization` 的 host-only VLIW
  实验已迁入 [`local_examples/`](local_examples/README.md)。这里保留 public /
  held-out controller 边界和统一 Plain Codex / Goal Plus 入口；旧的定制实验
  harness 不再由 Goal Plus core 仓维护。

## 固定验收门禁

每个 benchmark 按同一顺序推进：

1. `source_forked`：上游、fork、tracking branch 与许可边界已记录；实验 manifest 另存 resolved commit。
2. `environment`：依赖与任务数据可重复安装。
3. `official_verifier`：不依赖模型的确定性 baseline 能被官方 evaluator 接受。
4. `legacy_agent_smoke`：上游原生 agent/API 路径至少跑通一例，用于隔离环境问题。
5. `plain_codex`：Codex 在独立 workspace 中改 artifact，controller 能保存 JSONL、usage 和最终文件。
6. `goal_plus_codex`：Goal Plus 驱动 Codex lineage，候选、父子关系、验证与恢复状态可回放。
7. `matched_baseline`：plain / random / parallel / evolve / Goal Plus 使用相同模型、任务、evaluator-call 预算。
8. `campaign_ready`：subset、seeds、资源、反作弊与汇总协议冻结。

任何阶段都不能由“代码里看起来支持”直接跳成 `pass`。

## 范围与顺序

主顺序保持为：

1. ALE-Bench Lite
2. HeuriGym
3. Frontier-Engineering v1-lite
4. AutoLab CPU subset
5. SwarmResearch 15-task substrate（先 Math / ADRS / ALE 各一题）
6. Frontier-CS
7. EdgeBench open-source gradient subset
8. PERFOPT-Bench（等待公开 artifact 恢复）

SkyDiscover 是 search runtime，EvoX、AdaEvolve 与 OpenEvolve 是搜索方法；
它们不与 benchmark 混为一类。SwarmResearch 同时含方法实现和 15-task 论文
substrate，实验时也必须把这两个角色拆开。

## 统一控制面架构

绝大多数 benchmark 的差别在 native harness 和 evaluator，不在控制面的生命周期。
Codex 始终从本仓根目录启动；`bench-goal-plus` 管版本、实验协议、进程与统计，
上游 harness 继续拥有 task runtime 和 official judge：

```text
Codex 启动于 bench-goal-plus/
          │
          ▼
experiments/<benchmark>/experiment.py
  provision / doctor / prepare / run / status / stop / finalize
          │
          ▼
third_party/<benchmark>/  ← tracked fork branch / pinned dataset revision
          │
          ▼
benchmark-native harness
          │
     ┌────┴────┐
     ▼         ▼
 Work/runtime   Judge/evaluator
     │         │
     └────┬────┘
          ▼
runs/<benchmark>/<campaign-id>/
  manifests / prompts / logs / usage / artifacts / comparison
```

`third_party/` 是可重建依赖，不是实验现场；`runs/` 才是可恢复的 campaign
状态。controller 不重写 benchmark 的评分逻辑，也不把所有任务强塞进一个
artifact adapter。没有 Docker 的 benchmark 仍使用同一生命周期，只是
`Work/runtime` 与 `Judge/evaluator` 由 host process 承担。

对于不需要上游 checkout 的固定小任务，唯一例外是仓内 `local_examples/`：
它直接作为 task source，仍由同一 runner materialize 到 `runs/` 下的隔离
workspace。它不会进入正式 benchmark 数量，也不能替代 SForge hidden judge。

## 仓库结构

```text
benchmarks/registry.json       唯一状态源：上游、fork、branch、门禁、证据、下一步
benchmarks/datasets.json       SWE/Web/Security 数据集来源、实验角色与 panel 冻结状态
benchmarks/task-adapters.json  standalone task ID 到经校验 adapter 模块的注册表
docs/roadmap.md                分 benchmark 的推进计划与完成定义
docs/experiment-taxonomy.md    Agent 方案、搜索方法、runtime、benchmark 与 task pack 分类
docs/codex-run-contract.md     所有 benchmark 共用的 Codex 执行/证据契约
docs/docker-storage-plan.md    单 case 实测镜像、全量空间预算与 Linux campaign 规划
docs/benchmarks/               规模/时间总览与每套 benchmark 的代表 case 导读
docs/goal-plus-benchmark-experiment.md  Goal Plus 接入、并发、公平预算与逐 benchmark 对标协议
docs/generic-benchmark-support.md       通用 adapter/campaign、B0-B4 映射和未支持边界
docs/benchmark-datasets.md              SWE-EVO、CyberGym、WebArena 等数据集与 panel 目录
docs/openevolve-cpu-examples.md         OpenEvolve 无特殊硬件示例的主实验/诊断/暂缓分级
docs/reproducible-environment.md         新机器 bootstrap、doctor、workspace 与实验执行手册
environment/                             Python lock 与受管 fork branch manifest
third_party/                             所有 branch-tracked benchmark/search runtime 的统一 ignored checkout 根目录
local_examples/                          无 Docker 的固定 task replica；只作方法实验，不冒充正式 benchmark
experiments/openevolve_compare/          native OE / Plain Codex / Goal Plus+Codex / Goal Plus+Pi 同任务时限入口
experiments/benchmark_compare/             standalone benchmark 与 local task 的 Plain Codex / Goal Plus+Codex 统一入口
experiments/benchmark_campaign/            benchmark × condition × seed 通用 campaign、状态与报告
experiments/heurigym_compare/              上述通用实现的兼容入口
experiments/edgebench/                      SForge 原生 runtime/judge 的 campaign 控制、监控、停止与汇总
adapters/heurigym/                        HeuriGym workspace、官方 evaluator 与数据固定层
adapters/openevolve_examples/           OpenEvolve example catalog、workspace/evaluator/ticket/archive contract
scripts/run_codex.py           通用非交互 Codex runner，保存 JSONL、usage 与 manifest
scripts/openevolve_task.py     list/batch-seed-smoke/materialize/evaluate/archive OpenEvolve example task
scripts/repro_env.py           创建、fast-forward 并检查 `.bench-env/venv` 与 `third_party/` managed branches
scripts/status.py              校验 registry 并打印状态矩阵
evidence/legacy-smokes/        迁入的摘要、结果及 SkyDiscover 完整 checkpoint
legacy/direct-api/             原有 direct-API smoke 辅助脚本，作为环境基线
docs/legacy-smoke-runbook.md   已去除机器路径的旧实验复现说明
scripts/verify_legacy_smokes.py 迁移证据与可选上游 raw artifact 交叉验证
tests/                         不调用真实模型的 runner/registry 测试
```

上游仓库不作为 submodule 纳入；后续需要修改 fork 时，在 `.worktrees/` 创建干净工作区并 push 到 registry 指定 branch。下一次 `bootstrap` 会 fast-forward；历史实验仍由各自 manifest 中的 resolved commit 定位。

## 使用

统一 Agent Skill 入口和迁移边界见
[Agent Skill architecture](docs/agent-skill-architecture.md)。查看已登记 runner、target 和
Docker owner 后，可先做不执行的计划检查：

```bash
python3 scripts/bench.py catalog
python3 scripts/bench.py plan --preset edgebench-codex-2h
```

`start` 在 prepare 成功后写 `agent-run.json`；后续只需要 campaign path 即可执行
`status`、capability 允许的 `stop/resume`，以及终态后的 `finish`。

新机器先执行：

```bash
python3 scripts/repro_env.py bootstrap
python3 scripts/repro_env.py doctor
```

它会按 `environment/upstreams.json` 把所有 benchmark、OpenEvolve 和 Goal Plus
准备到本仓统一的 ignored `third_party/`，并按 `environment/requirements.lock`
创建 `.bench-env/venv`。只准备一个 benchmark 时可用
`bootstrap --only heurigym`；OpenEvolve/Goal Plus 作为公共 runtime 仍会自动加入。
controller、verifier、临时编译和子进程的 `TMPDIR`、`TMP`、`TEMP` 全部固定到
本仓 ignored `.tmp/`，不会依赖 `/tmp`、`/private/tmp` 或 `/var/tmp`。
`.venv/` 只是旧本机缓存，不属于复现契约；换机器必须重建 `.bench-env/venv`
和 `third_party/`，不能复制另一台机器的 virtualenv。

```bash
python3 scripts/status.py
python3 scripts/status.py --check
python3 -m unittest discover -s tests -v
```

通用 Codex runner 的最小形态：

```bash
python3 scripts/run_codex.py \
  --workspace /path/to/isolated-task-workspace \
  --prompt-file /path/to/prompt.md \
  --run-dir runs/<benchmark>/<run-id>
```

runner 不保存环境变量值；模型/provider、任务 commit 和 evaluator 仍必须由 benchmark adapter 写入 run manifest 扩展字段。

对已登记的 standalone benchmark 做 B0/B1/B3/B4 配对 campaign：

```bash
.bench-env/venv/bin/python experiments/benchmark_campaign/experiment.py prepare \
  --campaign-dir runs/benchmark-campaigns/local-vliw-shakedown \
  --benchmarks local-vliw --conditions B0 B1 B3 B4 --seeds 1 2 \
  --wall-time-seconds 360 --concurrency 2 --model gpt-5.6-sol

.bench-env/venv/bin/python experiments/benchmark_campaign/experiment.py run \
  --campaign runs/benchmark-campaigns/local-vliw-shakedown \
  --model gpt-5.6-sol

.bench-env/venv/bin/python experiments/benchmark_campaign/experiment.py status \
  --campaign runs/benchmark-campaigns/local-vliw-shakedown
```

B3 映射到 Goal Plus Search Space `observe`，B4 映射到 `enforce`；B2 和
way0 因运行时缺少对应的可见性开关而明确拒绝。完整设计、指标覆盖和后续
WebArena/SWE-EVO/CyberGym 接入边界见
[通用 Benchmark 支持](docs/generic-benchmark-support.md)。

场景候选数据集已经进入独立的可校验目录；这不会把尚未实现 native harness 的
SWE-EVO、CyberGym 或 BrowserGym 任务冒充成 standalone adapter：

```bash
python3 scripts/datasets.py validate
python3 scripts/datasets.py list --domain software --stage 1
python3 scripts/datasets.py show swe-evo
```

目录当前登记 SWE-EVO、RoadmapBench、SWE-bench Pro audited policy、
SWE-bench Verified、Cybench、CyberGym、WebArena 和 WorkArena L1。panel 状态、
revision/task-ID 冻结门槛及接入顺序见
[Benchmark 数据集目录](docs/benchmark-datasets.md)。

OpenEvolve task 的四路径对比入口见 [实验目录](experiments/openevolve_compare/README.md)。`prepare-batch` / `run-batch` 可一次展开并执行 12-task × 多方法 campaign；主实验固定相同 task/evaluator/model、总 wall budget `T` 和 live concurrency `K`。各方法的 evaluator calls、iterations 与 tokens/cost 在运行后报告，不用强行改造 Goal Plus 去模拟 OpenEvolve round。

EdgeBench 使用自己的 SForge harness，不走 standalone artifact adapter：

```bash
python3 scripts/repro_env.py bootstrap --only edgebench

.bench-env/venv/bin/python experiments/edgebench/experiment.py provision \
  --profile vliw-smoke
.bench-env/venv/bin/python experiments/edgebench/experiment.py doctor \
  --profile vliw-smoke
.bench-env/venv/bin/python experiments/edgebench/experiment.py prepare \
  --profile vliw-smoke --campaign-id vliw-matched-01
.bench-env/venv/bin/python experiments/edgebench/experiment.py run \
  --campaign vliw-matched-01 --detach
.bench-env/venv/bin/python experiments/edgebench/experiment.py status \
  --campaign vliw-matched-01
```

完整停止、恢复边界和汇总字段见
[EdgeBench campaign runbook](experiments/edgebench/README.md)。

没有 Docker 时，可以先用相同控制协议跑 local VLIW replica：

```bash
python3 local_examples/vliw_kernel_optimization/evaluate.py --cases both

.bench-env/venv/bin/python experiments/benchmark_compare/experiment.py prepare \
  --benchmark local-vliw --method goal-plus-codex \
  --wall-time-seconds 360 --soft-closeout-seconds 60 \
  --worker-runtime-seconds 120 --concurrency 2 --model gpt-5.6-sol
```

该路径输出 `cycles` raw metric，但 manifest 会固定写入
`source_kind=local_example` 和 `official_benchmark_comparable=false`，不能与
官方 EdgeBench score 混报。

## 旧资料边界

`mythink/agentic-scaling/benchmark-smoke` 的逻辑、复现说明和有价值的运行证据已全部迁移；旧目录可以删除。逐文件映射和删除门禁见 [迁移完成说明](docs/legacy-smoke-migration.md)，复现命令见 [legacy smoke runbook](docs/legacy-smoke-runbook.md)。后续状态和新实验只在本仓更新。

# bench-goal-plus

Goal Plus 的 benchmark 集成与实验控制仓。它把此前散落在 `mythink/agentic-scaling/benchmark-smoke`、各上游 checkout 和研究计划里的状态，收敛成可验证、可逐项推进的工程项目。

**基于 attitude 的 agent 预分析认为：核心关注，必须系统化推进——真正要证明的不是“Codex 能打开这些仓库”，而是同一任务、同一 evaluator、同一预算下，plain Codex 与 Goal Plus + Codex 的搜索轨迹和 best-seen 提升可以复现、计费并公平比较。**

## 当前结果

- 已跟踪 10 个 GitHub fork；EdgeBench fork 也已纳入统一版本清单。
- 11 个受管源码/runtime checkout 已全部收敛到 ignored `third_party/`；EdgeBench 可单独执行 `bootstrap --only edgebench`，其 SForge 与 Goal Plus exact commit、任务 revision、Codex auth policy 和单题镜像由同一 control plane 检查。
- PERFOPT-Bench 当前没有可 fork 的公开可执行 GitHub 仓库，只有 4open.science artifact 与宣传站，因此明确标为 `blocked`，不拿网站仓冒充 benchmark。
- ALE-Bench Lite、HeuriGym、AutoLab 已有本机官方 verifier / 远端模型 smoke 证据。
- ALE-Bench Lite `ahc027` 已完成首个真实 plain Codex smoke：`gpt-5.4-mini` 改写候选后 5/5 public-lite cases accepted，raw score 从 61,302,533 降到 55,181,186（该题越低越好，改善 9.99%）。
- OpenEvolve `function_minimization` 已通过通用 task adapter 完成 Plain Codex 闭环：复用原生 evaluator，`combined_score` 从 1.2147685971 提升到 1.4997641484（+23.46%），共 4 public + 1 final calls；这是接线 smoke，不是 matched OpenEvolve baseline。
- OpenEvolve 已筛出并批量接入 12 个 `cpu_portable` tasks：只使用标准库/NumPy/SciPy，不需要 GPU、NPU、下载数据集、网络服务、编译器或额外可执行软件。12/12 seed 通过官方 evaluator（合计 evaluator 时间 10.35s），12 × 4 共 48/48 方法单元也已批量 prepare；这 11 个新增任务当前是 evaluator/prompt/campaign ready，尚未冒充已完成真实模型 E2E。
- OpenEvolve `function_minimization` 已完成 [四路径首轮 smoke](evidence/runs/2026-07-22-openevolve-four-path-5m-summary.md)：统一 `gpt-5.6-luna/high`、`T=300s`、`K=2`。该轮保留 native OpenEvolve / plain Codex 结果，并暴露出 Goal Plus 仅靠 controller closeout 也可能误报完成的问题。
- Goal Plus + Codex/Pi 曾通过 [controller-prepared 严格重跑](evidence/runs/2026-07-22-goal-plus-codex-pi-strict-rerun.md) 验证底层 worker、verifier 和 promotion 能力；该入口现保留为历史诊断证据，不再作为标准主实验。标准入口改为 Plain Codex 使用 common task prompt，Codex + Goal Plus 只增加 `/goal-plus` 前缀和完整配置后缀，并让 Goal/Spec/Run 全部在计时后的自然流程中创建。
- Goal Plus + Codex 已完成 [自然 prompt 标准入口 E2E](evidence/runs/2026-07-22-goal-plus-codex-natural-prompt.md)：prepare 后不存在 `.gp/`，定时运行内自然创建 Goal/Spec/Run 和两个 Codex workers；`gpt-5.6-sol/high`、`T=300s`、`K=2` 下，`combined_score` 从 1.119176 提升到 1.499540（+33.99%），两个 worker 都提交 verifier 结果并完成 promotion/report。
- HeuriGym `operator_scheduling` 已完成 [Plain Codex / Goal Plus + Codex 首轮真实 E2E](evidence/runs/2026-07-22-heurigym-operator-scheduling-codex-goal-plus.md)：两者共享 `gpt-5.6-sol/high`、`T=300s`、`K=2`、common prompt 和官方五-case evaluator；seed `total_cost=138`，Plain Codex 得 62，Goal Plus + Codex 得 95。它是接线证据，不是单次方法排名。
- Standalone benchmark 已收敛到同一 [Plain Codex / Goal Plus + Codex runner](experiments/benchmark_compare/README.md)：当前支持 ALE-Bench Lite `ahc027`、AutoLab `toy_isa_opt`、Frontier-Engineering `MallocLab`、Frontier-CS `problem-0` 和 HeuriGym `operator_scheduling`；每题仍保留自己的 artifact、official evaluator、raw metric、方向、timeout 和资源要求。
- AutoLab host-portable smoke 已跑通：`gpt-5.6-sol/high`、`K=2` 下 Plain Codex 在 `T=240s` 从 `9220` 降到 `1547 cycles`；Goal Plus 在 `T=360s` 创建 2 个已绑定 Codex lineage，至少 1 个 worker 提交 verifier，但最终仍为 seed `9220`。这证明路径成立，不代表 Goal Plus 输赢。
- Frontier-Engineering MallocLab 的上游 evaluator 已在 macOS 通过 portable rebuild：seed `28/100`；Plain Codex `T=300s,K=2` 达到 `90/100`，Goal Plus `T=420s,K=2` 的 best verified/promoted 结果为 `89/100`。两者都通过 `11/11` traces；预算不同，仍只是各自接线 smoke。
- ALE-Bench Lite `ahc027` 的通用 Goal Plus 入口也已完成真实 E2E：`gpt-5.6-sol/high`、`T=480s`、`K=2` 下创建 2 个已绑定且均提交 verifier 的 Codex lineage，9 次 process-verifier iteration 后从 seed `55,181,186` 降到最终 `52,693,209`（越低越好，改善 `4.51%`）；本轮共记录 12 次 evaluator command/call，仍是接线证据而非 matched 方法排名。
- Frontier-CS problem 0 已完成 Docker host-capable 的两条真实路径：Plain Codex `T=180s,K=2` 最终 `93.4561753`（12 calls）；Goal Plus `T=420s,K=2` 创建 2 个已绑定、均有 verifier 的 lineage，7 次 process iterations 后 search best `93.3980341`、promotion gate `93.2217282`、独立 final `93.3097979`（10 calls）。该上游使用 clock-seeded 搜索，三次分数差异是已知噪声，不能把这轮当作方法排名。
- SkyDiscover/EvoX 已完成 DeepSeek OpenAI-compatible 的 1 iteration smoke，但还不是论文可比实验。
- 已在当前 Mac 为所有可执行 benchmark 建立代表 case 的环境证据：ALE、AutoLab、SwarmResearch、Frontier-CS 使用镜像，HeuriGym 与 Frontier-Engineering v1-lite 使用 host 环境；完整空间表见 [镜像空间与 Linux 规划](docs/docker-storage-plan.md)。
- 已建立 [Benchmark 快速导读](docs/benchmarks/README.md)：记录当前可跑题数、coverage/campaign 时间，并为 7 套 active benchmark 展开一个真实 case 的输入、agent 动作、期望输出和 verifier。
- Docker 已成为 registry 一等字段：`scripts/status.py` 直接显示
  `REQUIRED / NO / MIXED / N/A`；[Docker 依赖速查](docs/benchmarks/README.md#docker-依赖速查)
  明确没有 Docker 时仍可运行的 task 与不能替代的官方评分边界。
- 已建立 [Goal Plus 接入与并发实验协议](docs/goal-plus-benchmark-experiment.md)：区分 agent/evaluator/task 三层并发，定义 matched-budget baseline、逐 benchmark 整改和非 Pass@K 的验收门槛；OpenEvolve 自带 CPU 任务见 [示例审计](docs/openevolve-cpu-examples.md)。
- 已建立 [可移植复现环境](docs/reproducible-environment.md)：固定 Python 依赖及 OpenEvolve/Goal Plus commit，自动 bootstrap/doctor，并为四条独立路径生成隔离实验目录。Goal Plus 的 `.gp` 只存在于临时 task workspace。
- OpenEvolve example 的自然 `/goal-plus` 标准入口已成为统一模板；ALE-Bench Lite、HeuriGym、AutoLab、Frontier-Engineering 和 Frontier-CS 现在复用同一 common-prompt / Goal Plus-suffix 结构。
- EdgeBench 已接入 campaign controller：固定 fork 与 HuggingFace revision，按 profile 精确拉取任务/镜像，区分 Plain Codex 的 K 个独立 replica 与 Goal Plus 的 K 个 internal workers，并提供 `prepare / run / status / stop / finalize`。VLIW 已完成同模型、同 `T/K` 的真实 lifecycle E2E，judge lifecycle、evaluator calls 和 Codex session usage 均可回收；`T=120s` 尚不足以 dispatch Goal Plus worker，所以它仍不是方法效果对比。

## 固定验收门禁

每个 benchmark 按同一顺序推进：

1. `source_forked`：上游、fork、commit 与许可边界已记录。
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

SkyDiscover/EvoX 与 OpenEvolve 是 search backend，不与 benchmark 混为一类。

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
third_party/<benchmark>/  ← pinned fork / pinned dataset revision
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

## 仓库结构

```text
benchmarks/registry.json       唯一状态源：上游、fork、commit、门禁、证据、下一步
docs/roadmap.md                分 benchmark 的推进计划与完成定义
docs/codex-run-contract.md     所有 benchmark 共用的 Codex 执行/证据契约
docs/docker-storage-plan.md    单 case 实测镜像、全量空间预算与 Linux campaign 规划
docs/benchmarks/               规模/时间总览与每套 benchmark 的代表 case 导读
docs/goal-plus-benchmark-experiment.md  Goal Plus 接入、并发、公平预算与逐 benchmark 对标协议
docs/openevolve-cpu-examples.md         OpenEvolve 无特殊硬件示例的主实验/诊断/暂缓分级
docs/reproducible-environment.md         新机器 bootstrap、doctor、workspace 与实验执行手册
environment/                             Python lock 与 OpenEvolve/Goal Plus 固定版本 manifest
third_party/                             所有 pinned benchmark/search runtime 的统一 ignored checkout 根目录
experiments/openevolve_compare/          native OE / Plain Codex / Goal Plus+Codex / Goal Plus+Pi 同任务时限入口
experiments/benchmark_compare/             五套 standalone benchmark 的 Plain Codex / Goal Plus+Codex 统一入口
experiments/heurigym_compare/              上述通用实现的兼容入口
experiments/edgebench/                      SForge 原生 runtime/judge 的 campaign 控制、监控、停止与汇总
adapters/heurigym/                        HeuriGym workspace、官方 evaluator 与数据固定层
adapters/openevolve_examples/           OpenEvolve example catalog、workspace/evaluator/ticket/archive contract
scripts/run_codex.py           通用非交互 Codex runner，保存 JSONL、usage 与 manifest
scripts/openevolve_task.py     list/batch-seed-smoke/materialize/evaluate/archive OpenEvolve example task
scripts/repro_env.py           创建并检查可丢弃的 `.bench-env/venv` 与 `third_party/` pinned checkouts
scripts/status.py              校验 registry 并打印状态矩阵
evidence/legacy-smokes/        迁入的摘要、结果及 SkyDiscover 完整 checkpoint
legacy/direct-api/             原有 direct-API smoke 辅助脚本，作为环境基线
docs/legacy-smoke-runbook.md   已去除机器路径的旧实验复现说明
scripts/verify_legacy_smokes.py 迁移证据与可选上游 raw artifact 交叉验证
tests/                         不调用真实模型的 runner/registry 测试
```

上游仓库不作为 submodule 纳入；后续需要修改 fork 时，在 `.worktrees/` 创建干净工作区，并把 fork commit 回填到 registry。

## 使用

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

## 旧资料边界

`mythink/agentic-scaling/benchmark-smoke` 的逻辑、复现说明和有价值的运行证据已全部迁移；旧目录可以删除。逐文件映射和删除门禁见 [迁移完成说明](docs/legacy-smoke-migration.md)，复现命令见 [legacy smoke runbook](docs/legacy-smoke-runbook.md)。后续状态和新实验只在本仓更新。

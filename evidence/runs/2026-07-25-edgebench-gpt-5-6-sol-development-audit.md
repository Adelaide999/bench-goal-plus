# EdgeBench GPT-5.6-Sol 开发态 campaign 审计

本文记录 campaign
`edgebench-51-codex-gpt-5-6-sol-medium-2h-k1-c2-20260724-1811` 在完成前 14 个
cell 后的开发态诊断。该 campaign 继续运行；本文只冻结诊断快照，不作为最终汇总，
也不支持任何官方可比性或模型排名主张。

## 运行契约与快照

- control-plane commit：`04704a159b4bcf8a60aaf288ac0a7a572a2dc73d`；
- EdgeBench fork commit：`662e9ed273eb9bee724224bb2e36ce28d61040cb`；
- dataset revision：`47846a4c3669ad447e0ea984833b0d352460c5f9`；
- 方法：Plain Codex，`gpt-5.6-sol/medium`；
- 每题时间：7200 秒；题内 replica concurrency：1；跨题 cell concurrency：2；
- 快照状态：14 completed、2 running、35 prepared、0 failed、0 interrupted。

14 个 completed cell 均满足以下开发态完整性检查：

- `final_result.json` 存在且 `best_score` 非空；
- best round 在 `run_history.json` 中为 `status=completed`、`valid=true`；
- `final_archive.tar.gz` 存在；
- 实际 agent runtime 约为 7200 秒。

这证明 Work/Judge 容器、Codex、timeout closeout、Judge history 和最终归档链路真实
可用，但不证明运行协议与官方 leaderboard 一致。

## 与 GPT-5.5 @2h 的同量纲参考

下表把每题 raw metric 按当前 task JSON 换算到 EdgeBench 0--100，再与官方公开
51-task 曲线中 GPT-5.5 的 `@2h` 检查点比较。Borden 和 D-ABIC 的 native Judge
score 本身就是 0--100，task JSON 没有额外 `rescale`，因此按 identity 记录。

| Task | 当前 @2h | GPT-5.5 官方 @2h | 差值 |
|---|---:|---:|---:|
| `bipedalwalker_locomotion_rl` | 23.55 | 14.70 | +8.85 |
| `borden_source_inversion` | 78.50 | 20.10 | +58.40 |
| `dabic_gravity_inversion` | 27.95 | 15.90 | +12.05 |
| `graph_node_classification` | 60.96 | 54.70 | +6.26 |
| `ann_vector_search_qps` | 17.68 | 22.30 | -4.62 |
| `arc_compiler_runtime` | 52.12 | 55.50 | -3.38 |
| `exchange_core_throughput` | 94.33 | 15.40 | +78.93 |
| `ffmpeg_swscale_reimplementation` | 5.98 | 8.80 | -2.82 |
| `git_rewrite_in_zig` | 22.13 | 16.10 | +6.03 |
| `integer_compression_codec` | 43.00 | 61.10 | -18.10 |
| `juliet_vulnerability_analyzer` | 86.99 | 81.00 | +5.99 |
| `rust_multicrate_reconstruction` | 22.86 | 27.50 | -4.64 |
| `schemathesis_config_modernization` | 100.00 | 79.10 | +20.90 |
| `schemathesis_datagen_pipeline` | 100.00 | 54.60 | +45.40 |

在这个非随机的 14-task partial slice 上，当前均值为 52.58，官方 GPT-5.5 同题
`@2h` 均值为 37.63；9 题更高，5 题更低。这个 `+14.95` 不能解释为模型提升，
也不能外推到完整 51-task 均值。

## 已确认的协议差异

### 网络策略

当前 profile 强制 `internet=true`。官方 task definitions 中，50/51 题为
`internet=false`，仅 `college_english_exam_bank` 为 true。检查 Codex command
events 后确认网络权限被实际使用：

- `exchange_core_throughput` clone 了公开上游 GitHub repository；
- `schemathesis_config_modernization` 下载了上游 source files；
- `schemathesis_datagen_pipeline` 查询并下载了上游 PR、patch、tests 和 source；
- 快照时仍在运行的 `schemathesis_reporting_observability` 也在读取上游 source。

因此上述任务的结果不能作为官方完整性结果。未观察到 Codex `web_search` event
不能恢复可比性，因为 shell 网络访问已经发生。

### 资源、反馈频率和时间语义

官方 `examples/all-tasks-k8s/experiment-codex.yaml` 使用：

- Work 4 CPU / 16 GiB，Judge 4 CPU / 8 GiB；Lean/Coq 为 8 CPU，SMT 为 16 CPU；
- 默认 `submission_cooldown=120s`，D-ABIC 为 2160 秒，Schemathesis 为 216 秒；
- 12 小时 trajectory，并报告 2/4/6/8/10/12 小时 checkpoints；
- 每个 task/model 安排 3 条独立 trajectory，表格报告 valid runs 的均值。

当前 campaign 没有 CPU/memory quota，也没有 submission cooldown，且是知道自身只有
2 小时的独立 trajectory。例如 Borden 在两小时内产生 108 次 agent submissions，
远高于官方 120 秒 cooldown 的反馈频率。吞吐任务还会直接受无限 CPU 和宿主硬件
影响；`exchange_core_throughput` 的大幅正差尤其不能归因于模型。

### 汇总器缺口

`scripts/report_edgebench_scores.py` 在 task 没有 `judge.rescale` 时仍要求执行
rescale。Borden 和 D-ABIC 的 native score 已经是 0--100，但它们的
`score_0_100` 字段为 null；当前 reporter 会抛出 `ValueError`。原始 Judge result、
history 和 archive 都有效，但 campaign 最终自动 comparison 会把这两个 observation
写成 error，除非在最终汇总前修复 identity-score 处理并补测试。

## 论文源码核对

arXiv `2607.05155` 的 TeX source 于 2026-07-25 下载并通过 gzip 校验：

- source archive SHA256：
  `8193aeb41a3474690a40fac82e2ecbd53e651ab6b4759984b4c6845c04fbfd29`；
- `tables/leaderboard_table.tex`：GPT-5.5 在完整 134-task leaderboard 上为
  `@2h=36.8`、`@12h=48.4`；
- `sections/appendix.tex`：明确每个 task/model 安排 3 次运行，先换算到 0--100，
  再报告 valid-run mean 与 sample standard deviation；
- TeX appendix 的 per-task score tables 是 12 小时终点均值，不是 per-task 2 小时
  checkpoint。本文的 per-task `@2h` 参考来自同一官方 EdgeBench repository
  README 中的 51-task time curves。

## 开发态结论与正式对比待办

本轮保留并继续作为 exploratory development campaign。它证明 2-cell scheduler、
API/Judge bridge、镜像、依赖和 artifact lifecycle 能连续工作；所有成绩必须标注
`official_edgebench_comparable=false`。

正式对比前必须：

实现交接清单见
[`docs/edgebench-official-protocol-alignment-todo.md`](../../docs/edgebench-official-protocol-alignment-todo.md)。

1. 让 campaign 默认继承每题 `internet`，不得用 profile 全局强制开启；
2. 使用官方 Work/Judge CPU、memory、submission cooldown 和 task overrides；
3. 修复无 `rescale` 任务的 identity 0--100 汇总，并验证所有 51 题 reporter；
4. 冻结与官方一致的 12 小时 trajectory/checkpoint 语义；
5. 每个 task/model 至少运行 3 条独立 trajectory，并报告均值、方差和 valid coverage；
6. 分开报告模型、硬件、backend、evaluator calls、tokens、实际 wall time 与异常；
7. 在启动前做 profile-vs-official-YAML 的机器检查，任何差异都必须显式记录。

在完成这些对齐前，不使用本轮结果声称 GPT-5.6-Sol 相对 GPT-5.5 的官方提升。

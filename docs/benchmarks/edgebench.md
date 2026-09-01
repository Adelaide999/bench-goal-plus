# EdgeBench open-source subset

## 30 秒理解

EdgeBench 测的是 agent 能否在真实工程/研究 artifact 上持续改进，并由隔离的
hidden judge 给出 correctness 与连续分数。公开子集当前有 51 题，跨系统软件、
算法优化、形式化、仿真和交互环境；并非每题都适合当前 Mac。

对 Goal Plus 最有价值的是其中的 gradient cases：合法候选不只得到 pass/fail，
还得到可连续优化的 raw score。这样能区分共享证据、跨 lineage transfer 和
best-seen 搜索能力，而不只是 Pass@K。

| 项目 | 内容 |
|---|---|
| 公开范围 | 官方集合 51 题；当前可运行集合 50 题，本项目先冻结 8–12 个 gradient cases |
| Docker | **必需**；SForge 为每题启动 work container 与独立 hidden judge |
| Docker 空间 | VLIW 代表 case 的 work + judge 逻辑合计 `2.23 GB`；单 case 建议预留 `5 GB`，多题需 provision 后按 digest 实测 |
| 无 Docker 环境 | 不能运行或评分官方 EdgeBench；可运行仓内 VLIW local replica 做诊断 |
| 当前门禁 | VLIW 的环境、Plain/Goal Plus lifecycle 与 usage 回收已通 |
| 跟踪源码 | `ck0123/EdgeBench@mac`；campaign manifest 记录实际 commit |

## 代表 case：VLIW Kernel Optimization

### 输入是什么

任务 workspace 提供自定义 VLIW/SIMD simulator、kernel generator、
`solution.py`、public tests 与说明。agent 的自然任务正文来自固定 dataset
revision 的 task JSON：
实现并优化 `KernelBuilder.build_kernel`，只允许修改 `solution.py`。

### Agent 要做什么

生成正确的 instruction program，运行公开 verifier，分析 cycle bottleneck，并
迭代降低 simulator cycles。Plain Codex 的 K 条 replica 相互独立；Goal Plus 的
K 个 workers 共享 Search Evidence/Schema，但各自在隔离 candidate workspace
工作，只有 main session 能 promotion 后提交 hidden judge。

### 期待输出是什么

最终 artifact 是一个可执行且未修改测试/runner 的 `solution.py`。SForge 保存
`final_archive.tar.gz`、每轮 submission report、`final_result.json` 和完整 agent
输出；Goal Plus 额外保存 state archive。

### Verifier 如何评分

hidden runner 先检查所有 hidden cases correctness，再以 cycles 为 raw score，
方向是 minimize。SForge 使用 task JSON 中固定的 `log_min` rescale 把 raw
cycles 转成 EdgeBench 0–100；无效候选没有合法 cycle score。

## 实验怎么用

先使用 `vliw-smoke` profile 验证一题：

```bash
python3 scripts/bench.py plan \
  --benchmark edgebench --profile vliw-smoke \
  --campaign-id vliw-matched-01
python3 scripts/bench.py start \
  --benchmark edgebench --profile vliw-smoke \
  --campaign-id vliw-matched-01
python3 scripts/bench.py status \
  --campaign runs/edgebench/vliw-matched-01
```

Runner 当前声明六个 canonical methods：`plain-codex`、
`goal-plus-codex`、`plain-claude`、`plain-pi`、`goal-plus-pi` 和
`goal-plus-pi-provider`。Pi 的最小
profiles 是 `vliw-pi-sol-medium-local-smoke` 和
`vliw-goal-plus-pi-sol-medium-local-smoke`；后者固定 `K=2`、240 秒 worker
lease、每条 worker 至少 1 次正式 verifier、30 秒 verifier timeout 和 300 秒
finalization grace。Pi 需要 host
`~/.pi/agent/auth.json`（或 `SFORGE_PI_AUTH_FILE`）中的 `openai-codex` 登录。
这些 Pi profiles 当前是 wiring-ready，不代表已取得真实 E2E pass evidence。

`goal-plus-pi-provider` 用于 Pi built-in provider 或 models registry 中的显式 API provider，
不是“本地模型”含义。它不读取 `openai-codex` OAuth，要求 profile 的 model 使用
`PROVIDER/MODEL`。推荐的一小时 VLIW preset 是
`edgebench-vliw-goal-plus-pi-zai-glm-5-2-1h`，固定
`zai/glm-5.2/high`、`T=3600,K=2,C=1,R=1`，直接使用 `ZAI_API_KEY`。
`edgebench-vliw-goal-plus-pi-glm-provider-1h` 继续保留给需要自定义 base URL/wire API
的 `models.json` 路径。Pi built-in DeepSeek 等 provider 同理直接使用真实
`PROVIDER/MODEL` 和标准 key env，不需要改 adapter 名称。
这套 adapter 不依赖 macOS：Linux 服务器使用相同 registry 注入和 Work container
路径。provider registry 可选择 `anthropic-messages` 或
`openai-completions`/`openai-responses`，无需增加另一种 benchmark method。

profile 的 `protocol_source=edgebench-official-codex` 是协议资源来源标签：CPU/memory、
联网规则和 evaluator 周期来自官方 `experiment-codex.yaml`。实际运行 agent 由 method
和 model 决定，该字段不表示 Pi campaign 使用 Codex。

该 bootstrap 同时准备固定 SHA256 的 Rust 1.88.0 Linux x64 宿主缓存。Rust
任务会优先使用 Work/Judge image 内同版本工具链，仅在缺失或版本漂移时离线
注入；不会在 agent 或 hidden verifier 运行期间联网安装 compiler/crates。

正式对比固定 task/data revision、model/reasoning、总时间 `T` 和 live concurrency
`K`。Plain Codex 用 K 个 SForge replicas；Goal Plus 用一个 outer SForge run
与 K 个 internal workers。独立的 `cell_concurrency` 控制同时运行的不同题，默认
为 1，避免和题内 K 无意相乘。

`experiments/edgebench/profiles/full-codex-2h.json` 覆盖当前 50 个可运行的公开任务，固定
Plain Codex、`gpt-5.6-sol/medium`、每题 `T=7200s`、题内 `K=1`、跨题
`cell_concurrency=2`，并由 detached controller 同时执行两道不同题。Linux
rootless Docker 上的宿主 loopback API 和 Judge 通过 campaign-owned 随机端口桥
提供给容器；桥随 controller 生命周期关闭，API 密钥不落盘。

官方公开集合仍为 51 题，但 `order_addition_permutation_optimization` 当前 pinned
Judge 的 private score-helper SHA 与自检期望不一致。已知坏 revision 会在 profile
加载阶段被拒绝，该题不再测试；等待上游的新 Judge tag 与 dataset revision 后再恢复。

两小时 run 的普通任务可从原生 auto-eval 历史批量提取 1 小时等中间点，无需
重跑模型或 verifier：

```bash
.bench-env/venv/bin/python experiments/edgebench/timecurve.py extract \
  --campaign <campaign-id> --checkpoint-hours 1
```

输出为 campaign 内的 `timecurve/timecurve.json` 和 `timecurve/timecurve.csv`。
文字冒险的 game mode 没有 auto-eval，必须在 checkpoint 前另行启动 detached
watcher；完整命令、边界语义和缺失数据处理见
[`experiments/edgebench/README.md`](../../experiments/edgebench/README.md)。

### 无 Docker 的 local replica

仓内 [`local_examples/vliw_kernel_optimization`](../../local_examples/vliw_kernel_optimization/README.md)
保存了从固定 work/judge images 提取的 simulator、starter、public cases 和
controller-owned held-out cases：

```bash
python3 local_examples/vliw_kernel_optimization/evaluate.py --cases both
python3 scripts/bench.py start \
  --benchmark local-vliw --method plain-codex \
  --wall-time-seconds 360 --worker-runtime-seconds 120 \
  --live-search-concurrency 2 --model gpt-5.6-sol \
  --reasoning-effort medium
```

这条路径适合本机快速比较方法，但不是官方 host-only EdgeBench backend。
held-out cases 已从 agent workspace 中移除，却仍存在同一 Git 仓；拥有宿主
广域读取权的 agent 可以找到它们。因此结果必须保留
`official_edgebench_comparable=false`，不能与 SForge score 混报。

## 可复用对比数据

EdgeBench README 提供 open-source 51-task 的 model reference curves，fork 的
score reporter 会按任务和最近 checkpoint 保留官方参考。当前本地两条真实
VLIW smoke 为：

### Opus 4.8 对 GPT-5.5 的公开 51 题 headroom 标记

论文 Appendix 14.6 给出每个 task/model 在 12 小时终点的 0–100 mean 和样本标准差；
公开数据集 README 另给出 2/4/6/8/10/12 小时 checkpoint。以
`Opus - GPT-5.5 >= 5` 分作为 material headroom：

- 20/51 题在 2h 或 12h 至少一个 checkpoint 有 material headroom；
- 8 题在 2h 和 12h 都保持至少 5 分优势：
  `openttd_transport_ai`、`exchange_core_throughput`、`wesnoth_tactical_ai`、
  `apple_incremental_game`、`schemathesis_datagen_pipeline`、
  `nethack_dungeon_agent`、`vibrating_path_graph_coloring`、
  `order_addition_permutation_optimization`；
- 2h-only 有 4 题：`ad_placement_optimization`、
  `new_foundations_consistency`、`integer_compression_codec`、
  `git_rewrite_in_zig`；
- 12h-only 有 8 题：`jagua_nesting_optimization`、`ann_vector_search_qps`、
  `smt_solver`、`molecular_self_assembly`、`graph_node_classification`、
  `borden_source_inversion`、`wireless_electricity_layout`、
  `ffmpeg_swscale_reimplementation`。

优先用于 GPT + Goal Plus 的第一组是：

| Task | Opus-GPT @2h | Opus-GPT @12h | 12h 运行间波动 | Judge timeout | 选择理由 |
|---|---:|---:|---|---:|---|
| `schemathesis_datagen_pipeline` | +13.4 | +13.5 | 1-SD bands 不重叠 | 1800s | 结构化软件任务、可分解、反馈密集 |
| `ad_placement_optimization` | +21.2 | +4.8 | 12h 差距收窄 | 600s | 特别适合检验 Goal Plus 是否提升 2h 学习速度 |
| `apple_incremental_game` | +16.1 | +17.0 | 波动较大 | 600s | 低成本策略搜索，但必须重复验证 |
| `molecular_self_assembly` | +2.2 | +14.0 | 1-SD bands 不重叠 | 600s | 明显的晚期提升；先复现已有 `REVIEW_HIGH` 异常 |

`order_addition_permutation_optimization` 的历史 headroom 数据仍保留在 51 题论文参考中，
但因上述 Judge 资产缺陷不属于当前可运行候选，不能用于新 campaign。

`smt_solver` 和 `nethack_dungeon_agent` 的 12h gap 也较强，但单次 Judge timeout
分别为 7200s 和 3600s，不适合作为第一轮低成本筛选。`openttd_transport_ai`、
`ann_vector_search_qps` 的方差或 evaluator 成本同样偏高。

完整 51 题分组、2h/12h 分数、样本标准差、evaluator timeout 与 source hash 见
[`paper-opus-4.8-vs-gpt-5.5-headroom.json`](../../experiments/edgebench/references/paper-opus-4.8-vs-gpt-5.5-headroom.json)。

同一 task、同一 model 的时间增益使用离线筛选器计算；默认把 2h→12h 至少提升
10 个 EdgeBench 分数点视为大幅提升：

```bash
.bench-env/venv/bin/python experiments/edgebench/reference_gain.py \
  --start-hour 2 --end-hour 12 --min-gain 10
```

`--model GPT-5.5` 可只看一个模型；重复 `--model` 可选择多个模型；
`--min-model-count 3` 可要求同一 task 至少有三个所选模型达到增益阈值，从而筛掉
单模型偶然值；`--top` 限制展示行数；`--format json --output <path>` 生成机器可读
报告。工具从受管 EdgeBench checkout 的公开 51 题 checkpoint 表读取原始曲线，
在报告中记录 source SHA256，并把缺少任一 endpoint 的 pair 保留为 missing，而不是填成 0。
这些 checkpoint 是公开 model reference curve，用于筛选 time-scaling case；它们不是
逐次 run 配对后的因果增益，正式实验仍需固定同一协议并重复运行。

这个标记只回答“公开结果中是否存在更好的 task trajectory”。它不是 matched
Goal Plus effect：论文中的 Opus 主要使用 1M Claude Code，而 GPT-5.5 使用 256k
Codex。当前 profile 又是 `gpt-5.6-sol/medium,T=2h`。正式判断必须先跑同协议 Plain GPT
baseline；若它已达到论文 Opus@2h，则该题不再具有这个外部 headroom。随后固定同一
task、model、reasoning、T/K/C 和 evaluator，比较 Plain 与 Goal Plus；论文 Opus 分数
只保留为 external target，不作为 pass 阈值。

- Plain Codex `gpt-5.5`，`T=180s,K=1`：4941 cycles；
- Goal Plus + Codex `gpt-5.6-terra/high`，`T=3600s,K=3`：1878 cycles，
  EdgeBench score 57.9476。

它们的模型、T、K 不同，只能证明接线，不是方法效果对比。正式数据必须由同一
campaign profile 生成，并同时报告 evaluator calls、wall time、tokens/cost
coverage 和 Goal Plus lineage 统计。

统一 controller 另有一轮同模型、同 `T=120s,K=1` 的真实 lifecycle E2E：
Plain / Goal Plus 均完成 work container、owned judge、timeout closeout 和
finalize；两者 raw 都是 seed `147734`。Goal Plus 在短预算内创建了 Goal、
frozen spec 和 Search run，但尚未 dispatch worker，因此这轮只证明控制面与
telemetry，不用于方法排名。正式短 pilot 应至少使用 `T>=300s,K>=2`。

## 代码与证据

- [EdgeBench campaign controller](../../experiments/edgebench/README.md)
- [Host-only VLIW local replica](../../local_examples/vliw_kernel_optimization/README.md)
- [固定 profile](../../experiments/edgebench/profiles/vliw-smoke.json)
- [环境 doctor](../../evidence/environment/2026-07-23-edgebench-vliw-doctor.json)
- [真实接线 smoke](../../evidence/runs/2026-07-23-edgebench-codex-goal-plus-smokes.md)
- [fork](https://github.com/ck0123/EdgeBench)
- [官方数据集](https://huggingface.co/datasets/ByteDance-Seed/EdgeBench)

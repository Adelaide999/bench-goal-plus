# EdgeBench campaign controller

这个目录把 EdgeBench 纳入 `bench-goal-plus` 控制面，但不复制 SForge 已经做好的
容器、hidden judge、auto-eval、replica 和 final archive。控制面跟踪 source
branch、固定 data revision，生成实验单元，启动/监控进程，并把 SForge raw
artifact 汇总成同口径表；campaign manifest 记录实际 source commit。

## 方法与 K 的映射

| 方法 | SForge outer run | live concurrency `K` | 含义 |
|---|---:|---:|---|
| Plain Codex | `K` replicas | `replica-concurrency=K` | K 条互相独立的 trajectory，等价于 independent parallel baseline |
| Goal Plus + Codex | 1 replica | `budget.max_parallel=K` | 一个共享搜索状态中的 K 个 candidate workers |

两者固定同一 task definition、hidden judge、model、reasoning effort 和 wall budget
`T`。它们不强行匹配 evaluator calls 或 round；这些是运行后报告的行为量。

## 从新机器开始

```bash
python3 scripts/repro_env.py bootstrap --only edgebench

.bench-env/venv/bin/python experiments/edgebench/experiment.py provision \
  --profile vliw-smoke

.bench-env/venv/bin/python experiments/edgebench/experiment.py doctor \
  --profile vliw-smoke
```

`provision` 只下载 profile 需要的 task definitions，并只 pull 这些题的 work/judge
images。`doctor` 检查：

- EdgeBench 与 Goal Plus tracked branch、clean state 和当次 resolved commit；
- SForge entrypoint；
- Codex auth 文件存在性，但不读取或记录其内容；
- Docker daemon 与 `linux/amd64`；
- HuggingFace dataset revision；
- profile 中每题的精确 work/judge image tag。
- profile 含 Rust 任务时，启动实际 Work/Judge image，用非登录 shell 核对
  `cargo`/`rustc 1.88.0`；镜像不完整时要求宿主机固定 SHA256 的 Rust 缓存可用。

`bootstrap --only edgebench` 会按 rsproxy、SJTU mirror、官方源的顺序预下载
Rust distribution 到 `~/.cache/sforge/rust/`，最终统一核对官方 SHA256。正常发布
镜像已包含相同版本，因此运行时只做快速探测；
缺失或版本漂移时，SForge 才把缓存注入 Work/Judge。Rust compiler 和 crate
依赖都不会在任务容器内联网下载。

任务数据在 `third_party/edgebench/tasks/`，并写入该 checkout 本机
`.git/info/exclude`；它不会污染 fork，也不会让 managed checkout 误报 dirty。

## 准备和启动

```bash
.bench-env/venv/bin/python experiments/edgebench/experiment.py prepare \
  --profile vliw-smoke \
  --campaign-id vliw-matched-01 \
  --model gpt-5.6-terra \
  --wall-time-seconds 300 \
  --concurrency 2 \
  --cell-concurrency 1

.bench-env/venv/bin/python experiments/edgebench/experiment.py run \
  --campaign vliw-matched-01 \
  --detach
```

`prepare` 不启动容器、不调用模型，也不预建 Goal Plus state。每个
task × method 都得到一个 cell manifest，完整 campaign 位于：

```text
runs/edgebench/vliw-matched-01/
├── campaign.json
├── controller.json
├── profile.json
├── controller.log
├── comparison.json
├── comparison.md
└── cells/
    └── <task>--<method>/
        ├── cell.json
        ├── command.json
        ├── controller.log
        ├── summary.json
        └── sforge/runs/...     SForge 原始运行目录
```

`concurrency=K` 控制同一题内的 Plain Codex replicas 或 Goal Plus workers；
`cell_concurrency` 控制同时运行的不同 task × method cells，默认是 1。为了避免
无意中把两个并发层相乘，需要跨题并行时应在同一个 campaign profile 中显式设置
`cell_concurrency`，不要同时启动多个 controller。

Linux rootless Docker 无法从容器直接访问只监听宿主 loopback 的 API/Judge 时，
controller 会为 campaign 生命周期启动随机高端口的 `systemd-socket-proxyd` 桥，
并在结束或可恢复停止时关闭。API 配置按
`SFORGE_AGENT_* > OPENAI_* > CODEX_API_KEY` 解析；密钥只进入子进程环境，不写入
manifest 或命令记录。`college_english_exam_bank` 的 Judge 使用同一 API bridge，
并按 EdgeBench 官方配置固定 `SFORGE_JUDGE_MODEL=gpt-5.5`。

完整 51 题 Plain Codex 两小时 campaign 使用：

```bash
.bench-env/venv/bin/python experiments/edgebench/experiment.py doctor \
  --profile full-codex-2h
.bench-env/venv/bin/python experiments/edgebench/experiment.py prepare \
  --profile full-codex-2h --campaign-id <campaign-id>
.bench-env/venv/bin/python experiments/edgebench/experiment.py run \
  --campaign <campaign-id> --detach
```

该 profile 固定 `concurrency=1`、`cell_concurrency=2`，即每题一个 Codex
trajectory、同时跑两道不同题。它不设置 Docker CPU quota；在不支持 CFS quota
的 rootless daemon 上，两个 Work cell 和 Judge 使用宿主可调度 CPU，结果必须
记录为无 CPU quota 的本机运行。

## 监控、停止与恢复

```bash
.bench-env/venv/bin/python experiments/edgebench/experiment.py status \
  --campaign vliw-matched-01

.bench-env/venv/bin/python experiments/edgebench/experiment.py stop \
  --campaign vliw-matched-01 \
  --wait-seconds 20
```

`run --detach` 建立独立 process group，并记录 controller PID/PGID。`stop` 请求
controller 向所有 active cells 转发 `SIGINT`，让每个 SForge run 执行原生
closeout；停止请求后不再启动新 cell。超出等待时间只报告仍在运行，不会自动
hard-kill 或清理容器/目录。

恢复边界是 campaign/cell，不伪造同一 trajectory：

- controller 仍活着：只用 `status` 重新观察；
- SForge 已写 `final_result.json`：运行 `finalize`，不再调用模型；
- cell 被中断且没有 final artifact：保留原 cell，重新 `prepare` 一个新 campaign
  作为独立 attempt；
- 孤儿容器：先按 SForge run ID 人工确认，不自动重复启动同一个 cell。

## 汇总

```bash
.bench-env/venv/bin/python experiments/edgebench/experiment.py finalize \
  --campaign vliw-matched-01
```

`finalize` 遍历每条 replica 的 `final_result.json` 和 `run_history.json`，调用
fork 内的官方 score reporter，保留：

- raw score、metric direction、validity；
- EdgeBench 0–100 与 extended score；
- official reference curve comparison；
- actual runtime、rounds、agent/auto submissions、resume count；
- evaluator calls；
- Codex input/cached/output tokens 与 coverage；
- Goal Plus search runs、candidates、agent sessions 和 worker verifier runs。

Fork 让 Codex 以 JSONL 输出，并在容器 closeout 时只归档
`~/.codex/sessions/`，不复制 auth/config。若旧 run 没有这些 artifacts，
`usage.coverage` 会明确写成 `agent_output_only` 或 unavailable，不能把零 token
解释为零成本。

## Profile 扩展

`profiles/vliw-smoke.json` 是一题接线 profile。扩到正式 8–12 题时复制一个新
profile 并固定：

- `dataset_revision`；
- `task_ids`；
- `methods`；
- model/reasoning；
- `wall_time_seconds=T`、题内 `concurrency=K` 与跨题 `cell_concurrency`；
- judge concurrency、work/judge CPU；
- 每 worker 首次 lease。

不要修改 SForge task JSON 的 hidden judge 或 rescale；profile 只选择任务和资源。

真实 lifecycle smoke 与解释边界见
[`evidence/runs/2026-07-23-edgebench-codex-goal-plus-smokes.md`](../../evidence/runs/2026-07-23-edgebench-codex-goal-plus-smokes.md)。

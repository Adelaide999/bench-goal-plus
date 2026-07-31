# EdgeBench runner

EdgeBench 保留 native SForge lifecycle。控制面负责选择 profile/preset、部署依赖、启动和
监控 campaign；SForge 继续拥有 Work container、hidden Judge、任务隔离和最终归档。

## 执行前

1. 阅读
   [Host 与鉴权矩阵](../../../benchmark-setup/references/host-auth.md)。
2. 用 `catalog` 确认 `edgebench-native` 的 method 和 capability。
3. 用 preset 或 profile 冻结 task、method、model、reasoning 和 `T/K/C/R`。
4. 运行 `plan`，检查 native `provision → doctor → prepare → run --detach` 命令链。

## 已登记方法

| Method | SForge agent | `K` 的含义 |
| --- | --- | --- |
| `plain-codex` | `codex` | `K` 个独立 outer replicas |
| `goal-plus-codex` | `codex-goal-plus` | 一个 outer run 内 `K` 个 Goal Plus workers |
| `plain-claude` | `claude-code` | `K` 个独立 outer replicas |
| `plain-pi` | `pi` | `K` 个独立 outer replicas |
| `goal-plus-pi` | `pi-goal-plus` | 一个 outer run 内 `K` 个 Goal Plus workers |
| `goal-plus-pi-provider` | `pi-goal-plus-provider` | 与上一行拓扑相同，但 outer/worker 都使用显式 `PROVIDER/MODEL` API 路径 |

不要使用未登记的别名。method 必须在 plan 阶段通过 runner
`supported_methods` 校验。`goal-plus-pi` 专指 `openai-codex` OAuth；Z.AI 或
自定义 Anthropic/OpenAI-compatible endpoint 使用 `goal-plus-pi-provider`，且 model
必须写成精确的 `PROVIDER/MODEL`。
provider 的 wire API 由 Pi registry 决定：`anthropic-messages` 和
`openai-completions`/`openai-responses` 使用同一个 method。macOS 与 Linux
也使用同一 adapter；host 只提供 registry/credential，实际 agent 始终运行在
EdgeBench Linux Work container 中。

一小时 VLIW provider preset：

```bash
python3 scripts/bench.py plan \
  --preset edgebench-vliw-goal-plus-pi-glm-provider-1h
```

它固定 `T=3600,K=2,C=1,R=1`，使用 `glm-proxy/GLM-5.2`；实际 launch 前仍需按
K/C 门禁展示并确认解析结果。

## 完整 Codex campaign

```bash
python3 scripts/bench.py plan --preset edgebench-codex-2h
python3 scripts/bench.py launch --preset edgebench-codex-2h
```

该 preset 固定 51 tasks、Plain Codex、`gpt-5.6-sol`、`medium`、
`T=7200,K=1,C=2,R=1`。`C=2` 表示两个 task cells 并发，不是两个 candidate。

## 监控和停止

```bash
python3 scripts/bench.py status --campaign runs/edgebench/<campaign-id>
python3 scripts/bench.py stop --campaign runs/edgebench/<campaign-id>
```

status 必须保留 native campaign/cell/PID/trajectory 状态。Goal Plus cell 还应展示
candidate、worker session/handle、verifier ledger、剩余时间和最新 Judge submission。
stop 是保留 partial evidence 的 controller closeout；partial trajectory 不能被删除，
也不能被伪装成原 trajectory 的无损 resume。

## Goal Plus completion evidence

Goal Plus + Codex 的 session allocation 本身不是 worker launch：

- 至少记录 `K` 个不同的 spawned worker thread，或 `K` 个不同的 Codex host handle；
- 至少 `K` 个 candidate-bound verifier records；
- 必须有 promotion 和 official Judge trajectory。

Goal Plus + Pi 不使用 Codex collaboration events，必须持久化至少 `K` 个 candidate-bound
Pi sessions 和 verifier records，并同样保留 promotion 与 official trajectory。
缺失任何 required evidence 时 cell/campaign 为 `partial`。

## Finalize

```bash
python3 scripts/bench.py finish --campaign runs/edgebench/<campaign-id>
```

native finalizer 生成 `comparison.json` 和 native workbook；统一 report exporter 再生成
`report.md` 与 `<campaign-id>.xlsx`。不要直接修改 native artifacts 来改变结论。

只有调试 EdgeBench controller 本身时才直接运行
`experiments/edgebench/experiment.py --help`；正常用户流程始终使用 `scripts/bench.py`。

---
name: benchmark-run
description: 准备、启动、监控、停止、恢复或汇总 bench-goal-plus benchmark campaign。用户要求选择 native/common runner、按 registry 调度任意已登记 benchmark、固定 T/K/C/R、执行某个 campaign preset，或留下可复现 evidence 时使用。
---

# Benchmark 运行

先读 [concurrency-contract.md](references/concurrency-contract.md) 和
[runner-contract.md](references/runner-contract.md)，再按需读 [runner-map.md](references/runner-map.md)。
环境未通过 `$benchmark-setup` 的 doctor 时不得启动正式 run。

## 统一入口

```bash
python3 .agents/skills/benchmark-run/scripts/run_benchmark.py catalog
python3 .agents/skills/benchmark-run/scripts/run_benchmark.py plan \
  --benchmark <registered-id> ...
```

先用 `catalog` 选择 target；用 `plan` 审查 resolved contract 和完整命令链。
dispatcher 默认执行 bootstrap 和 doctor；native profile 还执行 provision。可以显式跳过
bootstrap/provision，但不得跳过 doctor。长运行是否 detach 由登记的 runner capability 决定，
不得自行拼后台 shell。

具体 campaign 只作为 preset/example。EdgeBench 51 题示例见
[edgebench-codex-2h.md](examples/edgebench-codex-2h.md)，不得据此推断本 Skill 只支持该配置。

## 通用流程

1. 冻结 task/evaluator、model、reasoning、`T/K/C/R`、seed、method 和 resolved commit。
2. 在 `benchmarks/runners.json` 解析 target/runner；使用 native controller、common matrix 或 OpenEvolve batch 的 `prepare`，确认 prepare 不调用模型且不预建 Goal Plus state。
   Common matrix 的普通方法运行使用 `--method plain-codex` 或 `--method goal-plus-codex`；只有做 B0-B4 消融实验时才使用 `--condition`。两者不能混用。
3. 启动 runner。长运行使用已有 detach/controller，不自行拼后台 shell。
4. 用统一 `status --campaign <path>` 读取 `agent-run.json` 和 native manifest。不要因为终端断开就重建 campaign。
5. 只在 capability 允许时调用 `stop` 或 `resume`。EdgeBench stop 后归档 partial，不伪称原 trajectory 可恢复；common/OpenEvolve batch 只补跑未完成 cell。
6. native final artifact 存在后再 `finalize`/`summarize`，再用 `$benchmark-report` 导出。

## 交付

返回 campaign id/path、profile、实际 `T/K/C/R`、controller PID/状态、监控命令、停止命令和报告命令。凭据只从继承环境或 Codex auth store 读取。

## Gotchas

- 只有 runner capability 中 `cell_concurrency=true` 且已有测试证据时才能接受 `C>1`。
- Plain Codex 的 `K` 是独立 outer trajectories；Goal Plus 的 `K` 是共享状态 internal workers。
- Goal Plus + Codex 的 session/候选记录只证明控制面已分配工作；还必须在顶层
  Codex JSONL 中看到至少 `K` 次成功的 `spawn_agent`，并在 `.gp` 中看到 worker
  verifier 证据，才能认为实际 worker 链路跑通。空 target 的 `wait` 不是启动证据。
- 不要启动多个 controller 来伪造 `C`；总并发必须由一个 campaign manifest 记录。
- 重新运行 interrupted cell 会产生新 attempt；不得覆盖或伪装成原 trajectory 的 resume。

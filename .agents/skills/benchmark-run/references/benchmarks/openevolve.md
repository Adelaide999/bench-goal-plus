# OpenEvolve batch runner

该 runner 复用 OpenEvolve `cpu_portable` task/evaluator substrate，分别运行 native
OpenEvolve、Plain Codex、Goal Plus + Codex 和 Goal Plus + Pi。共享的是 task、artifact、
evaluator 和预算，不把 Codex 嵌入 OpenEvolve controller。

## 当前 contract

- task set：`cpu_portable`；
- 不要求 Docker；
- 一个 campaign seed；
- `C=1`；
- 支持 `resume` 未完成 cells，不声明 detach/stop；
- native OpenEvolve、Pi 和 SkyDiscover 路径需要显式 OpenAI-compatible endpoint；
- Codex 可省略 `--api-base` 使用 native login，也可使用显式 custom provider。

鉴权差异见
[Host 与鉴权矩阵](../../../benchmark-setup/references/host-auth.md)。

## Plan

```bash
python3 scripts/bench.py plan \
  --benchmark openevolve-cpu-portable \
  --model <model> \
  --reasoning-effort medium \
  --wall-time-seconds 300 \
  --live-search-concurrency 2
```

默认 method set 由 runner contract 决定。若显式选择 method，必须属于
`benchmarks/runners.json` 的 `supported_methods`。

## 执行与证据

prepare 必须：

- 只物化 task/evaluator/workspace；
- 不调用模型；
- 不预建 Goal Plus `.gp`、goal、spec、run、candidate 或 session。

run 按 cell 保存失败，不删除 partial campaign。最终报告保留 native
`combined_score`、metric direction、evaluator calls、可获得的 usage/cost coverage 和
actual wall time。没有真实模型运行的 seed/materialization smoke 只能声明
task/evaluator ready。

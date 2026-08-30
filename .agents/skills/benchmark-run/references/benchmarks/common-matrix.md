# Common matrix runner

Common matrix 用于“一个可编辑 artifact + 一个 benchmark-owned evaluator”形态。每个
adapter 负责 materialize 和 evaluate；matrix controller 负责 method/seed/cell 生命周期
和统一 evidence。

## 适用条件

- task 能物化成隔离 workspace；
- evaluator 有机器可读 raw metric 和 direction；
- benchmark 不需要把复杂服务、hidden judge 或 native scheduler 交给本仓重写。

不满足这些条件时使用 native runner。

## 配置

必须显式解析：

- target；
- adapter 可选的 `--task-id`；不传时使用该 adapter 的默认 task；
- method 或 B0-B4 condition（二者不能混用）；
- model、reasoning、`T`、`K`、seed；
- adapter 的 Docker、artifact 和 evaluator contract。

当前 `common-matrix` 没有证明跨 cell 并发，固定 `C=1`。不要因为 EdgeBench 支持
`C>1` 就把它迁移到 common runner。

## 生命周期

```bash
python3 scripts/bench.py plan \
  --benchmark <id> \
  --method plain-codex \
  --model <model> \
  --reasoning-effort medium \
  --wall-time-seconds 300 \
  --live-search-concurrency 1

python3 scripts/bench.py launch <same-selection>
```

adapter 提供 task catalog 时，在 `--benchmark <id>` 后增加 `--task-id <task>`。
Goal Plus method 需要共享工具目录时增加 `--shared-dir`；Plain method 和 condition
campaign 不接受该选项。

Goal Plus cell 的精确宿主命令必须显式包含 `max_parallel=K`、
`workspace_backend=git_worktree`、`promotion_mode=apply`、
`strategy=agent_guided` 和
`workers=MODEL*K`，并用 `annotator=MODEL` 固定已配置的 ViewAgent。这些字段同时进入
manifest 的 `command_config`，不能只出现在目标
正文。其余 adapter/evaluator/SearchSpec-only 合同仍由共享 `render_goal` 正文生成。

common runner 当前不声明 detached controller。长任务应在受管理的 Agent/session 中运行，
不能自行拼 `nohup` 或多个 controller。

Codex method 可以使用 native Codex login；显式 OpenAI-compatible endpoint、Pi 和其他
API 方法按
[Host 与鉴权矩阵](../../../benchmark-setup/references/host-auth.md)
以及选中 controller 的 `--help` 配置。

## Target 差异

运行前从 [runner map](../runner-map.md) 进入对应 benchmark reference，确认：

- official task/case set；
- artifact 和允许编辑面；
- evaluator、raw metric 和 direction；
- Docker requirement；
- 当前 readiness 和已执行 evidence。

adapter/registry 存在不等于真实 E2E 已通过。

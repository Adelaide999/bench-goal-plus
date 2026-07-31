---
name: bench-goal-plus
description: bench-goal-plus 的端到端路由 Skill。用户提出完整 benchmark 请求、请求同时包含环境部署/启动/监控/报告，或还不知道应该使用哪个 benchmark workflow Skill 时使用。
---

# Bench Goal Plus 路由

这个 Skill 只负责识别任务阶段并路由，不复制平台配置、benchmark 命令或报告逻辑。
仓库的统一入口是：

```bash
python3 scripts/bench.py catalog
```

先读 [Agent lifecycle contract](references/agent-contract.md)，再按请求选择：

| 请求 | 使用的 Skill | 先读的 reference |
| --- | --- | --- |
| 新机器、依赖、Docker、Mac/Linux、OAuth/API | `benchmark-setup` | [host-auth.md](../benchmark-setup/references/host-auth.md)、[benchmark-matrix.md](../benchmark-setup/references/benchmark-matrix.md) |
| 选择 benchmark、冻结配置、启动、监控、停止、恢复 | `benchmark-run` | [runner-map.md](../benchmark-run/references/runner-map.md)，再读对应 benchmark reference |
| native finalize、`report.md`、XLSX、指标核对 | `benchmark-report` | [report-contract.md](../benchmark-report/references/report-contract.md) |
| 接入新 benchmark 或 task family | `benchmark-adapt` | [adaptation-checklist.md](../benchmark-adapt/references/adaptation-checklist.md) |

## 端到端请求

当一个请求覆盖完整生命周期时，按以下顺序组合 Skills：

1. `benchmark-setup`：确认 host、auth、Docker、upstream 和 doctor。
2. `benchmark-run`：执行 `plan`，确认 resolved method/profile 与 `T/K/C/R`，再
   `launch`。
3. `benchmark-run`：长任务返回 campaign path，并通过 `status` 继续监控。
4. `benchmark-report`：campaign 终态后执行 `finish` 并核对产物。

不要仅因 catalog、profile 或代码路径存在就声明 ready。返回实际命令、campaign path、
状态和 evidence；缺少真实执行证据时最多为 `partial`。

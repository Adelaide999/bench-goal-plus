---
name: bench-goal-plus
description: 端到端操作 bench-goal-plus benchmark control plane。用户要求从新机器部署环境、选择已登记 benchmark、启动或恢复 campaign、监控/停止长任务、执行 native finalize，并生成 report.md 与 campaign 命名 XLSX 时使用；也用于检查新 benchmark 是否完成 setup/run/report 注册。
---

# Bench Goal Plus Agent

从仓库根目录使用统一入口：

```bash
python3 .agents/skills/bench-goal-plus/scripts/bench.py catalog
```

先读 [agent-contract.md](references/agent-contract.md)。需要细节时再使用
`$benchmark-setup`、`$benchmark-run`、`$benchmark-report` 或 `$benchmark-adapt`；不要绕过
`scripts/bench.py` 另拼生命周期命令。

## 执行

1. 用 `catalog` 确认 target/preset。
2. 用 `setup ... --dry-run` 或 `plan ...` 审查依赖、Docker owner/mode、上游和完整命令链。
3. 短任务使用 `e2e`，它在前台完成 setup、prepare、run、finalize 和报告导出。
4. 长任务使用 `start`；只有声明 `detach=true` 的 runner 才会后台运行。保存 campaign path；
   `agent-run.json` 已记录后续命令。
5. 用 `status` 读取 native campaign 和 Agent 状态；按 capability 使用 `stop` 或 `resume`，不得删除 partial campaign。
6. campaign 终态后用 `finish`，统一执行 native finalize/summarize 和 Markdown/XLSX 导出。

## 交付

返回实际 target、profile/preset、campaign path、`T/K/C/R`、状态、恢复/停止命令、source
JSON、`report.md` 和 `.xlsx` 的绝对路径。只有实际执行且 evidence 存在时声明 `pass`。

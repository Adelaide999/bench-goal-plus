---
name: benchmark-report
description: 汇总 bench-goal-plus benchmark campaign 并导出证据可追溯的 Markdown 与 Excel。用户要求 report.md、以 campaign 命名的 .xlsx、EdgeBench 51 题汇总、跨方法比较或核对 raw metric、token、evaluator call、wall time coverage 时使用。
---

# Benchmark 报告

先读 [report-contract.md](references/report-contract.md)。报告只能消费 native finalizer 产生的 JSON evidence。

## 流程

1. 确认 campaign controller 不再运行。仍在运行时只报告状态，不导出“最终”报告。
2. 如果本 Skill 是由后台 campaign 的“当前进展/是否跑完”查询触发，且状态显示已到终态、`can_finalize=true`、尚未归档，则在同一轮直接完成 `finish`。不要把“可以执行 finish”作为交付终点；用户明确要求只读状态或不要归档时除外。
3. EdgeBench 调用 native `finalize` 生成 `comparison.json` 和 native campaign XLSX；generic campaign 调用 `summarize`；OpenEvolve 使用自己的 campaign report。统一导出器再从 source JSON 生成 `report.md` 和统一格式 XLSX。
4. 优先通过统一入口执行 native finalize + 导出：

```bash
python3 scripts/bench.py finish --campaign runs/<family>/<campaign-id>
```

只有单独重导出已 finalized evidence 时才直接调用 `scripts/benchmark_report.py`。

5. 保留 campaign 内的 source JSON 和 `report.md`。默认把 workbook 写为 campaign 内的 `<campaign-id>.xlsx`；用户指定交付目录时传 `--xlsx-out <path>`，不要硬编码机器专属路径。
6. 打开或解析 XLSX 验证 workbook 非损坏、行数与 JSON records/cells 一致、表头冻结且可筛选。
7. 再次读取 campaign 状态，分别汇报“执行终态”和“归档结果”，以及 final/partial 状态、有效结果覆盖、缺失 telemetry、protocol mismatch、产物绝对路径和 source JSON。

这里的“归档”仅指 campaign-local final evidence 与报告。`finish` 不修改
`benchmarks/registry.json`，也不把文件写入可提交的 `evidence/runs/`。当真实 run 是新
benchmark/method 的接入验收时，报告完成后继续路由到 `$benchmark-adapt`：审计并脱敏最小
证据、写入 method-specific `stage_evidence`，并在同一变更中更新 readiness。

## 状态表述

`finish` 是终态后的归档与报告阶段，不是 benchmark 仍在执行的信号。必须使用无歧义表述：

- 执行已结束但尚不具备归档条件：说明终态和缺失条件；
- 执行已结束且自动归档成功：说明已执行 `finish` 并列出产物；
- 执行已结束但归档失败：保留原始结果，单独说明归档错误。

不得只说“还没执行 finish”，以免被理解为 benchmark 尚未完成。

## 约束

- 保留 raw metric 和 direction；normalized score 或 directional gain 只能是附加列。
- 缺失 token、cost、evaluator call、runtime 不得填 0；保留空值和 coverage。
- 不把不同 task、evaluator、`T`、`K`、model 或 reasoning 的结果称为 matched comparison。
- 不修改 raw campaign artifact 来美化报告，不在 workbook 中写凭据或 secret-bearing command。
- 只有可复现命令和 evidence 文件都存在时才能声明 `pass`。

## Gotchas

- EdgeBench 的 paper/local reference 列是诊断比较，不自动构成 leaderboard 同口径结论。
- 一个 cell 没有 score 与得分为 0 不同；Excel 中前者必须为空。
- 旧 run 可能只有 agent output token coverage；不得外推为完整用量或成本。
- 外部交付路径不是 evidence 根目录；报告中的 run/evidence 链接仍指向原 campaign。

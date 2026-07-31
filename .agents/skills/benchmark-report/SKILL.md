---
name: benchmark-report
description: 汇总 bench-goal-plus benchmark campaign 并导出证据可追溯的 Markdown 与 Excel。用户要求 report.md、以 campaign 命名的 .xlsx、EdgeBench 51 题汇总、跨方法比较或核对 raw metric、token、evaluator call、wall time coverage 时使用。
---

# Benchmark 报告

先读 [report-contract.md](references/report-contract.md)。报告只能消费 native finalizer 产生的 JSON evidence。

## 流程

1. 确认 campaign controller 不再运行。仍在运行时只报告状态，不导出“最终”报告。
2. EdgeBench 调用 native `finalize` 生成 `comparison.json` 和 native campaign XLSX；generic campaign 调用 `summarize`；OpenEvolve 使用自己的 campaign report。统一导出器再从 source JSON 生成 `report.md` 和统一格式 XLSX。
3. 优先通过统一入口执行 native finalize + 导出：

```bash
python3 scripts/bench.py finish --campaign runs/<family>/<campaign-id>
```

只有单独重导出已 finalized evidence 时才直接调用 `scripts/benchmark_report.py`。

4. 保留 campaign 内的 source JSON 和 `report.md`。默认把 workbook 写为 campaign 内的 `<campaign-id>.xlsx`；用户指定交付目录时传 `--xlsx-out <path>`，不要硬编码机器专属路径。
5. 打开或解析 XLSX 验证 workbook 非损坏、行数与 JSON records/cells 一致、表头冻结且可筛选。
6. 汇报 final/partial 状态、有效结果覆盖、缺失 telemetry、protocol mismatch、产物绝对路径和 source JSON。

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

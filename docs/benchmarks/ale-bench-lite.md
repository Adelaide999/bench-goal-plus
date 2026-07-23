# ALE-Bench Lite

## 30 秒理解

ALE-Bench 把 AtCoder Heuristic Contest 变成 agent benchmark：agent 不是回答一道题的最终数值，而是编写一个能处理未知生成实例的程序。程序必须先合法，再按连续目标函数计分；agent 可以在 public cases 上得到反馈，但 private-lite 只用于最终比较。

| 项目 | 内容 |
|---|---|
| 正式范围 | Lite 10 题：`ahc008/011/015/016/024/025/026/027/039/046` |
| 候选 artifact | 通常为 C++20、Python 或 Rust 程序 |
| 指标 | task-native raw score；方向因题而异 |
| 典型反馈 | 编译结果、合法性、每个 public case 分数、聚合 raw score |
| Docker | **必需**；当前 official-lite 评分路径使用 C++ work image 和 judge image |
| 无 Docker 环境 | 可读题和 materialize，但不能通过当前支持路径获得官方分数 |
| 当前门禁 | 通用 Plain/Goal Plus runner 与 official-lite evaluator 已接；两条 Codex 路径都有真实 E2E 证据 |
| 固定源码 | `SakanaAI/ALE-Bench@f7d9279` |

它适合证明 Goal Plus 的点，不是“模型会不会写竞赛代码”，而是：相同模型和 evaluator-call 预算下，多 lineage、反馈利用、失败恢复和 best-seen 保留是否带来稳定 raw-score 提升。

---

## 代表 case：AHC027 机器人清扫路径

办公室是一个 `N×N` 网格，格子之间可能有墙，每个格子有不同的积尘速度。机器人从 `(0,0)` 出发，必须访问全部格子并回到 `(0,0)`；路线会无限重复，目标是最小化长期平均污垢。

### 输入是什么

被评测程序从标准输入读取一个生成实例：

```text
N
h[0] ... h[N-2]       # 横向墙，N-1 行长度 N 的 01 字符串
v[0] ... v[N-1]       # 纵向墙，N 行长度 N-1 的 01 字符串
d[0][0] ... d[0][N-1]
...
d[N-1][0] ... d[N-1][N-1]
```

- `20 ≤ N ≤ 40`。
- `h/v` 描述相邻格子之间是否有墙。
- `1 ≤ d[i][j] ≤ 1000`，值越大表示该格子越需要频繁访问。
- agent 不会拿到一个固定输入文件后硬编码答案；它要提交能处理一组 public/private seeds 的程序。

### Agent 要做什么

Agent 编辑 `solution.cpp`，实现一个通用路线构造器。一个最低可行版本可以构造从 `(0,0)` 开始的 DFS 树，遍历每条树边两次；进一步优化会考虑：

- 高频访问高 `d[i][j]` 区域；
- 缩短两次清扫同一格之间的间隔；
- 在墙约束下寻找较短闭合路线；
- 根据 public-case 反馈调整排序、局部搜索或时间预算；
- 保证内部搜索及时停止，避免在 200 个 private-lite cases 上逐个 TLE。

候选工作区只暴露题面、任务说明和可编辑源码；private 输入及最终 evaluator 不应进入 agent workspace。

### 期待输出是什么

编译后的候选对每个输入实例输出一行移动字符串：

```text
RRDDLUUL...
```

字符只能是 `U/D/L/R`，长度不超过 `100000`。路线必须：

1. 不穿墙、不越界；
2. 访问所有格子至少一次；
3. 最终回到 `(0,0)`。

### Verifier 如何评分

非法路线得到 WA。合法路线按重复路线稳定后的平均污垢 `S̄` 计绝对分，**越低越好**；ALE 再用历史 standings 转成 rank/performance。Lite 默认每次 public evaluation 使用 5 个 cases，本项目 smoke 的 final private-lite 使用 200 个 cases。

当前证据中，plain Codex 生成的候选在 5/5 public cases 上合法，raw absolute score 从 `61,302,533` 降到 `55,181,186`，改善约 `9.99%`。通用 adapter 复验同一候选仍得到 `55,181,186`；首次 Rust tool build 后，一次五-case warm evaluation 实测约 `11.08s`。通用 Goal Plus 入口随后在 `gpt-5.6-sol/high`、`T=480s`、`K=2` 下创建 2 个已绑定且均提交 verifier 的 lineage，记录 9 次 process iterations，最终选择并 promotion `52,693,209`，相对该 seed 再降低 `4.51%`。本轮总计记录 12 次 evaluator command/call，预算和旧 plain 证据不匹配，因此只证明 E2E 接线与搜索闭环。

---

## 实验怎么用

| 层级 | 建议 |
|---|---|
| 快速 coverage | 10 题 × 1 candidate × 5 public，最后每题只做一次 private-lite |
| 策略筛选 | 每题 10–20 evaluator calls，对比 random / parallel / evolve / Goal Plus |
| 正式报告 | 固定模型、public cases、private 只提交一次；同时报告 raw score、best-seen AUC、calls、tokens、wall time |

最危险的混淆是把更多 public evaluator calls 当成“搜索策略更好”。ALE 必须首先匹配 evaluator-call ledger，其次才比较模型调用和 token。

## 可复用对比数据

- 官方 standings、rank 和 performance 映射可直接复用。
- 官方 evaluator 和数据由 ALE-Bench 提供，不需要自造 judge。
- 论文/官方 repeated sampling、self-refine 参数可以作为 baseline 口径，但本机不适合直接跑每题几十候选的全量 campaign。

## 代码与证据

- 上游：[SakanaAI/ALE-Bench](https://github.com/SakanaAI/ALE-Bench)
- 本仓 adapter：[`adapters/ale/`](../../adapters/ale/)
- Plain/Goal Plus 统一入口：[`experiments/benchmark_compare/`](../../experiments/benchmark_compare/)
- Standalone E2E 汇总：[`evidence/runs/2026-07-23-standalone-benchmark-codex-goal-plus.md`](../../evidence/runs/2026-07-23-standalone-benchmark-codex-goal-plus.md)
- plain Codex 证据：[`evidence/runs/2026-07-21-ale-ahc027-plain-codex/`](../../evidence/runs/2026-07-21-ale-ahc027-plain-codex/)
- 镜像与机器证据：[`evidence/environment/2026-07-21-mac-representative-smokes.json`](../../evidence/environment/2026-07-21-mac-representative-smokes.json)

[返回 Benchmark 导读](README.md) | [下一篇：HeuriGym](heurigym.md)

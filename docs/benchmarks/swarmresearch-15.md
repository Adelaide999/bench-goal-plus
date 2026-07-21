# SwarmResearch 15-task paper set

## 30 秒理解

SwarmResearch 不是一套全新的 judge，而是一套多 agent 研究方法及其实验任务集。论文从 Math、ADRS 和 ALE 三类各选 5 题，共 15 题，让多个 researcher lineage 并行提出、实现、评估和共享发现。这里最有价值的是它的**实验组织方式**，以及已经公开的任务轨迹和 evaluator substrate。

| 项目 | 内容 |
|---|---|
| 论文任务集 | Math 5 + ADRS 5 + ALE 5，共 15 题 |
| 候选 artifact | Python/C++ 程序或 task-specific solver |
| 指标 | task-native continuous score；方向随题目定义 |
| 论文预算口径 | README 估算约 100 美元/题；论文在 50 美元 cutoff 报告结果 |
| 当前门禁 | Math `circle_packing` evaluator 已通；ADRS/ALE worker build context 待补 |
| 固定源码 | method `SakanaAI/SwarmResearch@cfdcb71`；tasks `SakanaAI/swarm-research-reproduce@e848d8d` |

15 个任务是：

- Math：`circle_packing`、`erdos_min_overlap`、`mmd_14_3`、`signal_processing`、`third_autocorr_ineq`；
- ADRS：`cloudcast`、`eplb`、`llm_sql`、`prism`、`txn_scheduling`；
- ALE：`ahc008`、`ahc015`、`ahc016`、`ahc025`、`ahc026`。

对 Goal Plus 来说，它不是必须照搬的 controller；关键是复用相同 15 个任务与 evaluator，把 Swarm、固定并行、EvoX 和 Goal Plus 的调度策略放到统一预算账本中。

---

## 代表 case：26-circle Packing

在单位正方形里放置 26 个互不重叠的圆，最大化半径总和。这是连续、非凸、局部最优很多的搜索问题，适合观察不同 lineage 是否真正发现互补结构。

### 输入是什么

这个任务没有每次变化的 stdin 实例。固定任务参数是：

```text
n = 26
container = [0, 1] × [0, 1]
objective = maximize sum(r_i)
```

Agent 工作区包含 `initial_program.py` 和任务说明。初始程序用中心圆加若干环构造坐标，再根据边界和相邻圆距离计算可行半径。

### Agent 要做什么

Agent 修改 `initial_program.py` 中的 evolve block，并实现：

```python
def run_packing():
    # return centers, radii, sum_radii
    ...
```

可探索方向包括初始几何结构、对称性破缺、局部坐标搜索、半径重估、随机重启以及不同 lineage 之间复用成功结构。最终 evaluator 只看 artifact，不接受“我认为这个布局更好”的文字论证。

### 期待输出是什么

`run_packing()` 返回：

- `centers`：shape 为 `(26, 2)` 的坐标数组；
- `radii`：shape 为 `(26,)` 的非负半径；
- `sum_radii`：候选声称的半径总和。

一个概念性返回值是：

```python
centers = [[0.5, 0.5], [0.2, 0.2], ...]
radii = [0.10, 0.08, ...]
return centers, radii, sum(radii)
```

### Verifier 如何评分

Evaluator 重新检查：

1. 数组 shape 和数值是否有效；
2. 每个圆是否完全位于 `[0,1]²`；
3. 任意两个圆是否不重叠；
4. 重新计算半径总和，不信任候选自报值。

合法时 `combined_score = sum(radii)`，**越高越好**，并输出 validity 和 eval time；非法或运行超时则失败。当前初始程序在本机 official evaluator 上得到 `0.9597642169962064`，`validity=1`。

---

## 实验怎么用

建议把它分成两层：

| 层级 | 目的 |
|---|---|
| 5-task pilot | Math/ADRS/ALE 各至少一题，先统一 task-native metric、超时和 evaluator-call ledger |
| 15-task final | plain Codex、fixed parallel、Swarm/EvoX、Goal Plus 在相同模型和预算下做正式比较 |

公开轨迹按每题首尾时间戳计算的 wall span：Math 合计约 `55.57h`、ADRS `11.73h`、ALE `9.62h`，串行总计约 `76.92h`。这些轨迹内部包含并行 researcher，不能解释为 76.92 个单 agent 小时；它们适合用于容量规划和行为分析，不适合作为唯一 compute 口径。

当前复现边界也要保留：Circle Packing 已能独立评分，但复现仓存在 package/import/bootstrap 不一致，ADRS/ALE 还缺共享 worker build context。修复这些 substrate 问题后，才能声称 15 题端到端可复现。

## 可复用对比数据

- 论文公开任务选择、最终分数和多 agent trajectory，可作为同任务对标资料。
- 轨迹可重算 proposal/experiment/success 的行为统计，但成本比较仍需重新统一 model pricing 和 evaluator calls。
- SkyDiscover/EvoX 与 Swarm 高度重合 Math、ADRS、ALE 任务，可作为额外 search baseline；不能因任务名相同就假设 evaluator 版本完全相同。

## 代码与证据

- 方法仓：[SakanaAI/SwarmResearch](https://github.com/SakanaAI/SwarmResearch)
- 复现任务仓：[SakanaAI/swarm-research-reproduce](https://github.com/SakanaAI/swarm-research-reproduce)
- 本机 evaluator 结果：[`evidence/environment/2026-07-21-mac-representative-smokes.json`](../../evidence/environment/2026-07-21-mac-representative-smokes.json)
- 历史 smoke 汇总：[`evidence/legacy-smokes/2026-07-20-summary.json`](../../evidence/legacy-smokes/2026-07-20-summary.json)

[上一篇：AutoLab](autolab-cpu.md) | [返回 Benchmark 导读](README.md) | [下一篇：Frontier-CS](frontier-cs-algorithmic.md)

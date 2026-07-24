# HeuriGym

## 30 秒理解

HeuriGym 是 9 道科学与工程组合优化题。Agent 的产物是一个可复用求解器：读取不同实例，输出合法解；verifier 先检查硬约束，再计算成本。它比一次性数学问答更适合验证“生成算法 → 执行 → 根据失败或成本继续改进”的 search loop。

| 项目 | 内容 |
|---|---|
| 正式范围 | 9 题，覆盖 EDA、调度、路由、图优化、生物与运输问题 |
| 候选 artifact | Python solver |
| 输出 | 每个实例对应一个结构化文本解 |
| 指标 | `valid` + task-native cost，方向通常是最小化 |
| Docker | **不需要**；使用 pinned Python 环境和已 bootstrap 的数据 |
| Docker 空间 | `0 GB`；Python venv 和数据属于 host 空间，不计入 Docker |
| 无 Docker 环境 | 可以运行当前 `operator_scheduling` 及后续 host Python 任务 |
| 当前门禁 | `operator_scheduling` 已完成 Plain Codex 与 Goal Plus + Codex 真实 E2E；其余 8 题待接 |
| 跟踪源码 | `ck0123/heurigym@main`；run manifest 记录实际 commit |

9 题包括 `operator_scheduling`、`egraph_extraction`、`global_routing`、`intra_op_parallel`、`crew_pairing`、`pickup_delivery_time_windows`、`pedigree`、`protein_sequence_design` 和 `technology_mapping`。

---

## 代表 case：Operator Scheduling

这是高层综合中的算子调度：给定有依赖的操作 DAG、每种操作的执行延迟和可用硬件数量，安排每个操作从第几个 cycle 开始，使总 latency 尽可能小。

### 输入是什么

一个真实 demo JSON：

```json
{
  "name": "input",
  "delay": {"mul": 3, "sub": 1},
  "resource": {"mul": 2, "sub": 1},
  "nodes": [["n1", "mul"], ["n2", "mul"], ["n3", "sub"]],
  "edges": [["n1", "n3", "lhs"], ["n2", "n3", "rhs"]]
}
```

- 两个乘法器最多可以并行执行两个 `mul`。
- `n1/n2` 延迟都是 3 cycles。
- `n3` 必须等待两个前驱完成。

### Agent 要做什么

Agent 编写通用 Python solver，而不是直接输出这个 demo 的三个数字。求解器需要：

1. 解析 DAG、资源类型、延迟和容量；
2. 构造满足 precedence 的初始 schedule；
3. 在每个 cycle 检查同类活跃操作数不超过资源上限；
4. 用 list scheduling、critical-path priority、局部移动或 CP/ILP 启发式降低 makespan；
5. 对 demo/eval 实例都生成相同格式的结果。

### 期待输出是什么

每行是 `node_id:start_cycle`：

```text
n1:0
n2:0
n3:3
```

这里 `n1/n2` 并行开始，`n3` 在两个乘法完成后开始，总 latency 为 `4`。

### Verifier 如何评分

Verifier 分两层：

- **合法性**：对每条边检查 `start(src)+delay(src) ≤ start(dst)`；对每个 cycle 检查活跃资源数不超过容量。
- **成本**：`max(start(node)+delay(resource))`，即最后一个操作结束的 cycle，**越低越好**。

当前 adapter 固定五个 public demo cases。故意串行的 seed 在五题上的
aggregate `total_cost=138`；它是环境/合法性基线，不代表最优解。

---

## 实验怎么用

HeuriGym 最有价值的观测不是最终 cost 一项，而是 Goal Plus 是否能修复这些明确失败：

- solver 语法或导入错误；
- 缺少 node 或输出格式错误；
- precedence violation；
- resource over-allocation；
- 解合法但 latency 很差。

标准入口已经不是“给 HeuriGym 内部再塞一个 Codex provider”，而是让
benchmark controller materialize 相同 workspace：Plain Codex 直接接收 common
task prompt；Goal Plus + Codex 仅增加 `/goal-plus` 与完整条件约束。两边都调用
同一个 HeuriGym verifier/evaluator。

首轮真实 smoke 使用 `gpt-5.6-sol/high`、`T=300s`、`K=2`：Plain Codex 从
138 降到 62；Goal Plus + Codex 降到 95。Goal Plus 自然创建 2 个 candidate
和 2 个已绑定 Codex session，其中 1 个 worker 在 deadline 前提交 verifier，
被选中的 `c002` 正是这个 worker-verified candidate。这个单次结果只证明两条
链路已通，不能解释为 Plain Codex 方法优于 Goal Plus。

下一阶段应先重复 `operator_scheduling` 多个 seed，并补原生 HeuriGym agent
baseline，再扩展其余 8 题。当前每个候选程序对每个 case 的 timeout 是 10 秒；
全 9 题 campaign 的真实时间需要在 Linux 上实测后冻结。

## 可复用对比数据

- 仓库自带问题数据、verifier、evaluator 和部分 ILP/Gurobi baseline 生成代码。
- 各题目标函数不同，因此总榜必须保留 raw cost；归一化只能作为附加指标。
- 论文结果可用于任务级 sanity check，但 Goal Plus 的主要 baseline 应是同模型、同 3-iteration 预算的原生 agent。

## 代码与证据

- 上游：[cornell-zhang/heurigym](https://github.com/cornell-zhang/heurigym)
- 可复现入口：[`experiments/heurigym_compare/README.md`](../../experiments/heurigym_compare/README.md)
- 首轮 Plain/Goal Plus 证据：[`evidence/runs/2026-07-22-heurigym-operator-scheduling-codex-goal-plus.md`](../../evidence/runs/2026-07-22-heurigym-operator-scheduling-codex-goal-plus.md)
- 历史 smoke：[`evidence/legacy-smokes/heurigym-operator-scheduling-demo.output`](../../evidence/legacy-smokes/heurigym-operator-scheduling-demo.output)
- 统一环境证据：[`evidence/environment/2026-07-21-mac-representative-smokes.json`](../../evidence/environment/2026-07-21-mac-representative-smokes.json)

[上一篇：ALE-Bench Lite](ale-bench-lite.md) | [返回 Benchmark 导读](README.md) | [下一篇：Frontier-Engineering](frontier-engineering-v1-lite.md)

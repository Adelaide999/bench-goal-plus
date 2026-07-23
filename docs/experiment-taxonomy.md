# 实验对象分类：Agent 方案、搜索方法与 Benchmark

本仓同时管理“用什么方法搜索”和“在哪些任务上评分”，但两者不是同一类
对象。判断一个实验时，先按下面四层拆开：

```text
Benchmark / task
  ALE、HeuriGym、Frontier-Engineering、AutoLab、Frontier-CS、EdgeBench
          ↓ 提供输入、可编辑 artifact、evaluator 和 raw metric
Agent / search method
  Plain Codex、Independent Parallel、Goal Plus、OpenEvolve、EvoX、Swarm
          ↓ 决定如何产生、选择和延续候选
Runtime / host
  Codex CLI、Pi、Goal Plus runtime、SkyDiscover、OpenEvolve、SForge
          ↓ 负责启动模型、进程、workspace 和上游 harness
bench-goal-plus
  固定版本、预算 T/K、运行生命周期、usage/evaluator ledger 和结果汇总
```

同一个 benchmark 可以交给多种方法；同一种方法也应该跨多个 benchmark
验证。不能把 SkyDiscover/EvoX 的一次 Circle Packing smoke 计成新增了一套
benchmark。

---

## Agent 与搜索方案

这里的“方案”是实验中被比较的处理方式。模型和 benchmark 不属于这一列。

| 方案 | 类型 | 核心行为 | 当前接入边界 |
|---|---|---|---|
| Plain Codex | 单 agent baseline | 一个 Codex lane 直接修改 artifact 并调用 verifier | standalone 五题和 EdgeBench VLIW 已有真实 E2E |
| Independent Parallel Codex | 固定并行 baseline | `K` 个互不共享信息的 Plain Codex lane，最终按同一 evaluator 选 best | standalone runner 与 EdgeBench 已支持；当前 `plain-codex,K>1` 就是该口径 |
| Goal Plus + Codex | 本项目目标方案 | Goal Plus 管理 `K` 条 lineage、共享 Search Evidence/Schema、验证并 promotion | standalone 五题和 EdgeBench VLIW 已有真实 E2E |
| Goal Plus + Pi | host 变体/诊断方案 | Goal Plus 搜索逻辑不变，worker host 换成 Pi | 当前主要用于 OpenEvolve example 四路径入口，不计作独立搜索方法 |
| OpenEvolve | 进化搜索方法及参考 runtime | population/island 式生成、评估和保留候选 | 已有统一外层 `T/K` runner 和 12 个 CPU-portable task；正式 matched 结果与 usage coverage 待补 |
| EvoX | 搜索方法 | 运行中继续演化“进化策略本身” | 仅在 SkyDiscover runtime 上完成 Circle Packing 1-iteration compatibility smoke |
| SwarmResearch / Swarm | 多 agent 搜索方法 | 多 researcher lineage 并行提出、实现、评估和共享发现 | 论文方法与轨迹可分析；本仓尚未打通同口径 15 题方法复现 |
| AB-MCTS | 树搜索 baseline | 在候选树上分配扩展与评估预算 | Frontier-Engineering 上游原生支持；尚未成为本仓统一 baseline |
| Random / basic evolve | 低复杂度 baseline | 随机候选或固定进化规则 | 规划项；用于确认复杂方案不是只靠更多采样获胜 |

`Codex` 和 `Pi` 更准确地说是 agent host；`Goal Plus`、`OpenEvolve`、
`EvoX`、`Swarm` 才决定搜索和候选协作方式。实验名称仍使用
`Goal Plus + Codex`，是为了同时说明搜索方案和实际 host。

---

## Framework、方法和任务包的关系

| 名称 | 正确分类 | 它不是什么 | 本仓如何使用 |
|---|---|---|---|
| SkyDiscover | 搜索实验 framework/runtime | 不是 benchmark | 用它启动 EvoX；其仓库也附带 Math、ADRS、ALE 等任务入口 |
| EvoX | SkyDiscover 中实现的搜索方法 | 不是 benchmark | 作为 Goal Plus/OpenEvolve 的方法 baseline 候选 |
| OpenEvolve | 搜索方法及参考 runtime | 它的 `examples/` 整体不是正式 benchmark | 原生方法 baseline；同时借用筛选后的 example task 做接线和机制实验 |
| SwarmResearch | 方法仓 + 论文实验组织 | 不是一套全新的统一 judge | 方法作为 Swarm baseline；Math/ADRS/ALE 15 题作为可复用实验 substrate |
| SForge | EdgeBench 原生运行/评分 harness | 不是 agent 方案 | 管 EdgeBench work container、hidden judge 和 archive |
| bench-goal-plus | 实验控制面 | 不替代任何 benchmark evaluator | 管 pinned checkout、workspace、`T/K`、进程、usage 和结果 |

OpenEvolve 的 12 个 `cpu_portable` examples 与 SkyDiscover 的 Circle Packing
可以本机运行，但它们应标为 **method-repo task pack / diagnostic task**。除非
另有独立论文、固定数据版本和评分协议，不把它们计入“正式 benchmark 套数”。

`local_examples/vliw_kernel_optimization` 同属这一层：它是从 EdgeBench 固定
镜像提取的 host-only replica，用于快速比较 Plain Codex、Goal Plus 和后续
OpenEvolve/EvoX。它复用 `cycles` 语义，但没有 SForge 的容器隔离，不能记为
官方 EdgeBench 结果。

---

## 正式 Benchmark 与实验 substrate

| 对象 | 分类 | 当前计划中的作用 |
|---|---|---|
| ALE-Bench Lite | 正式 benchmark | 10 道启发式编程任务，观察连续 raw score 搜索 |
| HeuriGym | 正式 benchmark | 9 道约束优化任务，观察 solver 合法性和成本改进 |
| Frontier-Engineering v1-lite | 正式 benchmark | 10 道真实工程 artifact 优化任务 |
| AutoLab | 正式 benchmark | 长时自主实验和系统性能优化 |
| Frontier-CS | 正式 benchmark | 大规模开放算法题与 partial score |
| EdgeBench | 正式 benchmark | 隔离 artifact、真实 runtime 和 hidden judge |
| PERFOPT-Bench | 正式 benchmark，但 artifact 阻塞 | 真实性能优化；等公开可执行 artifact 恢复 |
| SwarmResearch 15-task set | 论文实验 substrate | 复用 Math 5 + ADRS 5 + ALE 5；同时对比 Swarm、EvoX、Goal Plus |
| OpenEvolve CPU examples | method-repo task pack | 快速接线、机制诊断和第一轮 OpenEvolve matched pilot |
| SkyDiscover Circle Packing | method-repo task | EvoX compatibility smoke，不单独算一套 benchmark |
| Local VLIW replica | local task replica | 无 Docker 的搜索方法对比；结果不计入官方 EdgeBench |

Benchmark 的本机可运行状态见
[Benchmark 导读：本机可直接运行什么](benchmarks/README.md#本机可直接运行什么)；
方法预算和并发协议见
[Goal Plus benchmark 接入与并发实验协议](goal-plus-benchmark-experiment.md)。

# Benchmark 导读与完整运行规模

这里回答两个问题：每套 benchmark 实际在测什么，以及当前 Mac 能否把一个正式子集或 track 全部跑完。每篇子文档都按同一顺序展开：**任务边界 → 一个真实 case → 输入 → agent 动作 → 期望输出 → verifier → Goal Plus 实验价值**。

“完整运行”分为两种口径：

- **coverage run**：每题至少产生一个候选并经过官方 verifier，用于确认接线和任务覆盖。
- **search campaign**：按 benchmark 默认或论文预算反复生成、验证、保留 best-seen，用于比较 Goal Plus、plain Codex、parallel、EvoX/OpenEvolve。

---

## Docker 依赖速查

这里的结论按 **bench-goal-plus 当前支持的可评分路径** 标记，而不是只看上游
仓库里是否存在 Dockerfile。`混合` 表示当前已有无 Docker 的单题入口，但完整
论文/多题路径仍依赖容器。

| Benchmark / task set | Docker | 没有 Docker 时能否跑 | 边界 |
|---|---|---|---|
| HeuriGym | 不需要 | **可以** | 使用 pinned Python 环境和已 bootstrap 的数据 |
| Frontier-Engineering MallocLab | 不需要 | **可以** | 需要本机 C 编译器和 `make`；其余 v1-lite 任务依赖另行冻结 |
| AutoLab `toy_isa_opt` | 不需要 | **可以** | 当前 host-portable adapter 需要 C 编译器和 `make` |
| OpenEvolve `cpu_portable` 12 题 | 不需要 | **可以** | 标准库、NumPy、SciPy；不含被筛掉的特殊软件/数据任务 |
| SkyDiscover/EvoX Circle Packing smoke | 不需要 | **可以** | EvoX 框架本身可用 Python 跑；换任务后重新检查 evaluator |
| AutoLab CPU subset / Harbor 正式路径 | 混合 | **不能完整跑** | 代表题可 host 跑，但完整 paper-compatible task 环境使用容器 |
| ALE-Bench Lite | **需要** | **不可以评分** | official-lite evaluator 需要 C++ work image 和 judge image |
| SwarmResearch 15 paper substrate | **需要** | **不可以正式复现** | paper-compatible task/evaluator 路径是容器化的 |
| Frontier-CS Algorithmic | **需要** | **不可以评分** | 当前 problem-0 adapter 需要 pinned judge image 和 Docker socket |
| EdgeBench | **需要** | **不可以评分** | SForge 需要 work container 与独立 hidden-judge container |
| PERFOPT-Bench | 未知 | 不可运行 | executable artifact 尚未公开，暂时无法确认 |

因此，无 Docker 环境优先跑：
`HeuriGym → Frontier-Engineering MallocLab → AutoLab toy_isa_opt →
OpenEvolve cpu_portable → SkyDiscover/EvoX Circle Packing`。启动 agent 前可用
`docker info` 判断 Docker 是否可用；失败时不要准备表中标为“需要”的任务。

---

## 当前规模与时间

以下估算基于 16 GiB Intel Mac、8.4 GB Docker VM、单 worker 串行执行。没有
Docker 的机器只适用上表“不需要”路径。模型延迟、候选超时和首次依赖下载会
造成较大波动，因此这里给区间而不是伪精确值。

| Benchmark 范围 | 题数 | 当前准备度 | Coverage run | Search campaign |
|---|---:|---|---:|---:|
| ALE-Bench Lite | 10 | 环境、官方 verifier、plain Codex 已通 | 单候选/题约 3–5 小时；只扫 verifier 约 20–40 分钟 | 约 31 candidates/题时，串行约 60–100 小时 |
| HeuriGym 全集 | 9 | 环境和 1 题已通；其余数据待下载 | 单候选/题约 1–2 小时 | 默认 3 iterations，约 3–6 小时 |
| Frontier-Engineering v1-lite | 10 | MallocLab 已通；其余 9 题 runtime 待安装 | 环境安装加单候选/题约 3–8 小时 | 100 iterations/题，约 40–120 小时 |
| AutoLab CPU subset | 25 | `toy_isa_opt` 已通；其余镜像待构建 | 10 分钟/题的 bounded coverage 约 6–10 小时 | 20 题 × 2h + 5 题 × 4h = 60 agent-hours；加 verifier 约 2.5–3 天 |
| SwarmResearch 论文任务集 | 15：Math 5 + ADRS 5 + ALE 5 | Circle Packing 已通；ADRS/ALE worker 布局待修 | evaluator-only 约 2–6 小时 | 公开轨迹任务 wall span 串行合计约 76.9 小时 |
| Frontier-CS Algorithmic | 当前固定版本 188 | problem-0 已通；其余 task 尚未 materialize | reference/verifier 全扫约 1–3 小时 | 单次 agent/题约 10–30 小时；20 calls/题可能 100–300 小时 |
| EdgeBench open-source subset | 51；先选 8–12 gradient cases | VLIW 的环境、Plain Codex、Goal Plus 已通；统一 controller 已接入 | 单候选/题通常 10 分钟–2 小时，取决于任务 | 正式 profile 建议每题 1–2 小时；8–12 题约 16–48 method-hours |

这些数字不应直接拿来横向比较方法速度：ALE 的一次 candidate 会跑多个 generated cases，AutoLab 的“2 小时”是长时 agent budget，Swarm 的公开 wall span包含并行研究者，而 Frontier-CS 的题量远大于其他集合。公平实验最终应以 **evaluator calls + wall time + model calls/tokens** 三组预算同时报告。

Goal Plus 的逐项接入改造、`K/E/Q` 三层并发和 matched-budget baseline 见 [Goal Plus benchmark 接入与并发实验协议](../goal-plus-benchmark-experiment.md)。OpenEvolve 自带的无特殊硬件任务见 [OpenEvolve CPU 示例审计](../openevolve-cpu-examples.md)。

---

## 快速导读

| 文档 | 它真正测什么 | 代表 case |
|---|---|---|
| [ALE-Bench Lite](ale-bench-lite.md) | LLM/agent 能否为未知启发式实例编写高分程序，并利用 public feedback 继续优化 | AHC027 机器人清扫路径 |
| [HeuriGym](heurigym.md) | 能否从约束和目标函数生成通用启发式求解器，而非只回答一个固定答案 | HLS Operator Scheduling |
| [Frontier-Engineering v1-lite](frontier-engineering-v1-lite.md) | 能否在真实工程 artifact 上持续改进连续分数 | MallocLab 动态内存分配器 |
| [AutoLab CPU subset](autolab-cpu.md) | 长时 agent 是否会实验、验证、保留最好实现并抵抗 shortcut | Toy ISA 流水线调度 |
| [SwarmResearch 15](swarmresearch-15.md) | 多 lineage / swarm 搜索是否能在大搜索空间中累积有效发现 | 26 圆装箱 |
| [Frontier-CS Algorithmic](frontier-cs-algorithmic.md) | 面向开放算法研究问题生成可执行程序，并从连续 partial score 改进 | Polyomino Packing |
| [EdgeBench](edgebench.md) | 在真实隔离 artifact + hidden judge 上利用连续 feedback 持续优化 | VLIW Kernel Optimization |

PERFOPT-Bench 因缺少可执行公开 artifact 继续挂起，不进入本文档集。SkyDiscover/EvoX 和 OpenEvolve 是 search backend，不作为 benchmark 单独写 case 文档。

---

## 本地展开顺序

1. **HeuriGym 9 + ALE Lite 10**：题量小、CPU 可跑，先形成 19 题的完整 coverage。
2. **Frontier-Engineering v1-lite 10**：补齐 runtime 后，将本地完整 coverage 扩到 29 题。
3. **AutoLab 只选 6–10 个 CPU case**：先验证 persistence，不在 Mac 上消耗完整 60 小时。
4. **SwarmResearch 15**：修好统一 evaluator/worker 后作为最终大实验 substrate。
5. **Frontier-CS 选 10 题**：保留 188 题 track 作为题库，不在本地对所有方法全扫。
6. **EdgeBench 先冻结 8–12 个 gradient cases**：Mac 只做单题接线，正式多方法 campaign 放到 Linux。

空间与 Linux 节点规划见 [Docker 镜像空间计划](../docker-storage-plan.md)，工程门禁以 [`benchmarks/registry.json`](../../benchmarks/registry.json) 为唯一状态源。

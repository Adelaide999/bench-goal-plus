# Frontier-Engineering v1-lite

## 30 秒理解

Frontier-Engineering 面向真实工程优化：候选通常是源码、设计参数或算法 artifact；基线已经能运行，agent 的任务是在 read-only verifier 下持续提高连续分数。v1-lite 是官方挑选的 10 题渐进式子集，特意避开“一次过关或永远过不了”的硬门槛题。

| 项目 | 内容 |
|---|---|
| 完整 benchmark | v1 共 47 题、5 类工程方向 |
| 本项目范围 | 官方 v1-lite 10 题 |
| 候选 artifact | 代码或 task-specific 工程 artifact |
| 指标 | 每题 raw score + Medal Score；本项目优先 raw score |
| Docker | 当前 MallocLab **不需要**；本机 C 编译器 + `make` 即可 |
| 无 Docker 环境 | 可以跑 MallocLab；其余 9 题仍需逐题确认 runtime，不据此宣称全套可跑 |
| 当前门禁 | MallocLab host evaluator 与 Plain/Goal Plus runner 已接；其余 9 题 runtime 未冻结 |
| 跟踪源码 | `ck0123/Frontier-Engineering@main`；run manifest 记录实际 commit |

v1-lite 涵盖 MallocLab、量子路由、JobShop、库存优化、电池快充、机械臂周期、全息聚焦、无线仿真、反应优化和拓扑优化。

---

## 代表 case：ComputerSystems/MallocLab

Agent 要把一个正确性和效率都较差的动态内存分配器改好。它不是生成一个 stdout 答案，而是改写 `mm.c`，然后由真实 C 编译器和 `mdriver` trace suite 检查。

### 输入是什么

对 agent 而言，输入是一个小代码仓：

- 可编辑：`malloclab-handout/mm.c`；
- 固定接口：`mm_init/mm_malloc/mm_free/mm_realloc`；
- read-only harness：`Makefile`、`memlib`、`mdriver` 和 traces。

一个短 trace 的内容如下：

```text
20000                 # 建议 heap 大小
6                     # block id 数
12                    # 操作数
1                     # 权重
a 0 2040              # allocate id=0, size=2040
a 1 2040
f 1                   # free id=1
a 2 48
...
```

完整评测包含 11 个 traces，覆盖 malloc/free，以及最后两个 realloc traces。

### Agent 要做什么

Agent 在 `mm.c` 的 evolve block 内实现分配器策略，例如：

- block header/footer 和 16-byte alignment；
- implicit/explicit free list；
- first-fit、next-fit 或 segregated lists；
- split 和 coalesce；
- 原地扩展或移动式 `realloc`；
- 在空间利用率和吞吐之间取舍。

Agent 可以反复 `make && ./mdriver -V`，根据具体 trace 的 correctness error、utilization 和 throughput 改进。

### 期待输出是什么

最终产物仍是 `mm.c`，必须保持四个函数签名：

```c
int mm_init(void);
void *mm_malloc(size_t size);
void mm_free(void *ptr);
void *mm_realloc(void *ptr, size_t size);
```

运行阶段没有自由格式输出；`mdriver` 调用这些函数并产生 trace 结果。

### Verifier 如何评分

Verifier 先 `make clean && make`，再运行 `./mdriver -V`，解析：

- correctness / 每个 trace 是否通过；
- space utilization；
- Kops throughput；
- 最终 `score / 100`。

本机 baseline 结果是 `28/100`，通过 `6/11` traces。通用 Plain Codex smoke 在 `gpt-5.6-sol/high`、`T=300s`、`K=2` 下达到 `90/100` 并通过 `11/11` traces；Goal Plus 的 `T=420s`、`K=2` smoke 创建 2 个已绑定且均提交 verifier 的 lineage，最终 `89/100`、同样通过 `11/11`。预算不同，因此只证明两条 E2E 路径。这个低但非零的连续分数非常适合测试 Goal Plus 是否能沿着“先修合法性，再做性能”逐步搜索。

---

## 实验怎么用

先不要直接跑官方 `100 iterations × 10 tasks`。建议：

1. MallocLab 上做 plain Codex 与 Goal Plus 各 10–20 evaluator calls；
2. 冻结 raw-score parser、编译失败和 trace failure 分类；
3. 补齐其余 9 题 runtime，做 `iterations=0` shipped-baseline validation；
4. 单候选覆盖 10 题后，再选择进入 100-call campaign 的策略。

v1-lite 环境安装加单候选覆盖预计 3–8 小时；官方 100 iterations/题在本机串行约 40–120 小时。

## 可复用对比数据

- 官方提供 v1/v1-lite leaderboard、raw results 和冻结的金银铜阈值。
- `baseline_archive/` 保存发布模型的候选 artifact，适合做可复评分比较。
- 本项目应优先报告 raw score 和 best-seen curve；Medal Score 用于跨题汇总，不能取代原始工程指标。

## 代码与证据

- 上游：[EinsiaLab/Frontier-Engineering](https://github.com/EinsiaLab/Frontier-Engineering)
- Plain/Goal Plus 统一入口：[`experiments/benchmark_compare/`](../../experiments/benchmark_compare/)
- Standalone E2E 汇总：[`evidence/runs/2026-07-23-standalone-benchmark-codex-goal-plus.md`](../../evidence/runs/2026-07-23-standalone-benchmark-codex-goal-plus.md)
- 本机结果：[`evidence/environment/2026-07-21-mac-representative-smokes.json`](../../evidence/environment/2026-07-21-mac-representative-smokes.json)

[上一篇：HeuriGym](heurigym.md) | [返回 Benchmark 导读](README.md) | [下一篇：AutoLab](autolab-cpu.md)

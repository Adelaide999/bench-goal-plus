# Frontier-Engineering v1-lite

## 30 秒理解

Frontier-Engineering 面向真实工程优化：候选通常是源码、设计参数或算法 artifact；基线已经能运行，agent 的任务是在 read-only verifier 下持续提高连续分数。v1-lite 是官方挑选的 10 题渐进式子集，特意避开“一次过关或永远过不了”的硬门槛题。

| 项目 | 内容 |
|---|---|
| 完整 benchmark | v1 共 47 题、5 类工程方向 |
| 本项目范围 | 默认 v1-lite CPU subset 9 题；完整 10 题显式 NVIDIA CUDA opt-in |
| 候选 artifact | 代码或 task-specific 工程 artifact |
| 指标 | 每题 raw score + Medal Score；本项目优先 raw score |
| Docker | 当前路径均 **不需要**；由仓库内受管 uv runtime 执行。CUDA 是独立的宿主机要求 |
| Docker 空间 | `0 GB`；2026-08-07 Linux host checkout + 3 个 uv runtime 实测约 12 GiB |
| 无 Docker 环境 | 默认只选择 9 个 CPU task；不执行 `nvidia-smi`、CUDA probe 或 RobotArm evaluator |
| 当前门禁 | CPU 默认 9 题；10/10 shipped baseline 曾在 8×V100 主机通过；EnergyStorage Plain Codex native smoke 已通过 |
| 跟踪源码 | `ck0123/Frontier-Engineering@main`；run manifest 记录实际 commit |

v1-lite 涵盖 MallocLab、量子路由、JobShop、库存优化、电池快充、机械臂周期、全息聚焦、无线仿真、反应优化和拓扑优化。官方环境矩阵把
`Robotics/RobotArmCycleTimeOptimization` 放进 GPU batch，因此默认 CPU profile
排除这一题。

## 当前 native 接入

统一 target 是 `frontier-engineering`，runner 是
`frontier-engineering-native`。旧的 `frontier-engineering-malloclab` 仍保留为
common runner 的单题回归 smoke，不能代表完整 v1-lite。

当前 native runner 支持 `plain-codex`、`goal-plus-codex` 和
`goal-plus-pi`。冻结 profile 包括：

- `energy-storage-codex-smoke`：电池快充单题，`T=300, K=1, C=1, R=1`，
  作为首选接入验收；
- `jobshop-codex-smoke`：JobShop 单题，`T=300, K=1, C=1, R=1`；
- `v1-lite-cpu-codex-1h`：默认 9 个 CPU task，每题
  `T=3600, K=1, C=1, R=1`；
- `v1-lite-codex-1h`：完整 10 题，显式 `nvidia-cuda-opt-in`，额外包含
  RobotArm。

每个 profile 必须声明 `accelerator_policy`。`cpu-only` 在加载 profile 时直接拒绝
`KernelEngineering/*`、`Aerodynamics/CarAerodynamicsSensing`、RobotArm 和
Quadruped；不会等到 evaluator 才报 CUDA 错误。带 CUDA task 的 profile 只能显式使用
`nvidia-cuda-opt-in`。只读 `check` 只展示 task 选择与 GPU probe 将在 doctor 执行；完整
`setup/doctor` 必须先通过 `nvidia-smi`，再用对应受管 runtime 验证
`torch.version.cuda`、`torch.cuda.is_available()` 和非零 device count。任何检查失败都
阻止 seed evaluator，controller 不会安装或修改 NVIDIA driver/CUDA。

环境由三个受管 runtime 组成：`frontier-eval-driver`、`frontier-v1-main` 和
`frontier-v1-summit`。2026-08-07 的 Linux doctor 在 upstream commit
`e3fa29c193356af2ce1ec8b3d23ab1a2e2410071` 上对 10 题逐题执行 shipped
baseline，全部返回 `valid=1`、`timeout=0` 和官方 `combined_score`。该验收主机有
8 张 Tesla V100，RobotArm 的 NVIDIA driver 和 PyTorch CUDA runtime 可用。这证明完整
10 题路径在该主机已通，但不改变后续 campaign 默认只选择 9 个 CPU task 的策略。

2026-08-07 的首个真实 native Agent smoke 使用
`EnergyStorage/BatteryFastChargingSPMe`、`plain-codex`、`gpt-5.6-sol/medium` 和
`T=300, K=1, C=1, R=1`。官方 evaluator 将 seed `66.163564` 提高到
`121.206310`，directional gain 为 `55.042745`；整条 trajectory 声明 21 次
evaluator 调用，最终改进出现在 `298.593s`。这证明 Plain Codex 单题路径，不能
替代 Goal Plus、`K>1` 或完整 10 题 campaign 的验收。

```bash
python3 scripts/bench.py check \
  --benchmark frontier-engineering --profile v1-lite-cpu-codex-1h
python3 scripts/bench.py setup \
  --benchmark frontier-engineering --profile v1-lite-cpu-codex-1h
python3 scripts/bench.py plan \
  --preset frontier-engineering-energy-storage-codex-smoke
```

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

本机 baseline 结果是 `28/100`，通过 `6/11` traces。旧 common runner 的 Plain Codex smoke 在 `gpt-5.6-sol/high`、`T=300s`、`K=2` 下达到 `90/100` 并通过 `11/11` traces；Goal Plus 的 `T=420s`、`K=2` smoke 创建 2 个已绑定且均提交 verifier 的 lineage，最终 `89/100`、同样通过 `11/11`。预算不同，因此这些历史结果只证明 MallocLab 单题的两条 E2E 路径，不能替代新 native runner 的验收。这个低但非零的连续分数非常适合测试 Goal Plus 是否能沿着“先修合法性，再做性能”逐步搜索。

---

## 实验怎么用

先不要直接跑官方 `100 iterations × 10 tasks`。建议：

1. EnergyStorage native Plain Codex 的 `plan -> launch -> status -> finish` 已完成；
2. 下一步用同一 task 验收 Goal Plus 的实际 subagent 数量与 `K` 一致；
3. 固定 task、evaluator、model、reasoning 和 `T/K/C/R` 后做 matched comparison；
4. 再从默认 9 个 CPU task 扩到多 seed 或更长 wall-time campaign；只有明确需要时才
   对完整 10 题 profile 做 CUDA opt-in。

当前完整环境约 12 GiB。默认 `v1-lite-cpu-codex-1h` 在 `C=1` 下每种方法每个
repeat 需要至少 9 agent-hours；显式 GPU profile `v1-lite-codex-1h` 需要至少
10 agent-hours，另加最终 evaluator 和归档时间。

## 可复用对比数据

- 官方提供 v1/v1-lite leaderboard、raw results 和冻结的金银铜阈值。
- `baseline_archive/` 保存发布模型的候选 artifact，适合做可复评分比较。
- 本项目应优先报告 raw score 和 best-seen curve；Medal Score 用于跨题汇总，不能取代原始工程指标。

## 代码与证据

- 上游：[EinsiaLab/Frontier-Engineering](https://github.com/EinsiaLab/Frontier-Engineering)
- Native controller：[`experiments/frontier_engineering/`](../../experiments/frontier_engineering/)
- 默认 CPU doctor：[`evidence/environment/2026-08-07-frontier-engineering-cpu-default-doctor.json`](../../evidence/environment/2026-08-07-frontier-engineering-cpu-default-doctor.json)
- Native Plain Codex smoke：[`evidence/runs/2026-08-07-frontier-engineering-energy-storage-plain-codex/summary.json`](../../evidence/runs/2026-08-07-frontier-engineering-energy-storage-plain-codex/summary.json)
- 旧 MallocLab common runner：[`experiments/benchmark_compare/`](../../experiments/benchmark_compare/)
- Standalone E2E 汇总：[`evidence/runs/2026-07-23-standalone-benchmark-codex-goal-plus.md`](../../evidence/runs/2026-07-23-standalone-benchmark-codex-goal-plus.md)
- 本机结果：[`evidence/environment/2026-07-21-mac-representative-smokes.json`](../../evidence/environment/2026-07-21-mac-representative-smokes.json)

[上一篇：HeuriGym](heurigym.md) | [返回 Benchmark 导读](README.md) | [下一篇：AutoLab](autolab-cpu.md)

# Frontier-CS Algorithmic

## 30 秒理解

Frontier-CS 把开放式计算机科学问题封装成可执行 judge。Algorithmic track 不是传统“写出正确算法就满分”：许多题允许合法的近似解，并按解质量给连续 partial score，因此 agent 可以在多轮反馈中持续改进程序。

| 项目 | 内容 |
|---|---|
| 当前固定 Algorithmic track | 188 题 |
| 本项目本机范围 | 先 materialize problem 0，再选 5 个高 Pass@1 + 5 个低 Pass@1 |
| 候选 artifact | 读取任意实例的可编译程序，通常为 C++ |
| 指标 | checker-native partial score；每题方向由 statement/checker 定义 |
| Docker | **必需**；当前 problem-0 使用 pinned compile/checker judge image |
| 无 Docker 环境 | 可 materialize 和写候选，但不能通过当前官方 checker 路径评分 |
| 当前门禁 | problem 0 direct official checker、Plain/Goal Plus runner 和 partial-score parser 已通；两条 Codex 路径都有真实 E2E |
| 跟踪源码 | `ck0123/Frontier-CS@main`；run manifest 记录实际 commit |

Frontier-CS 还包含 Research 和 2.0 类任务；它们有不同依赖与硬件边界，不混入本页的 188 题 Algorithmic 规模估算。

---

## 代表 case：Problem 0 / Pack Polyominoes

给定成千上万个小 polyomino，把它们经过翻转、旋转和平移后放进一个矩形，要求互不重叠并尽量缩小矩形面积。

### 输入是什么

候选程序从标准输入读取：

```text
n
k_1
x_11 y_11
...
x_1k1 y_1k1
k_2
...
```

- `100 ≤ n ≤ 10000`；
- 每个 piece 由 `1..10` 个整数格坐标定义；
- 当前 materialized testdata 的第一行是 `3920`，但 agent 要写能处理任意合法实例的程序，不能只提交这一个实例的固定 placement。

真实输入开头类似：

```text
3920
8
0 0
0 1
1 1
2 1
2 2
3 0
3 1
4 1
10
...
```

### Agent 要做什么

Agent 编写一个通用 packing program，决定：

- 输出矩形宽 `W` 和高 `H`；
- 每块 polyomino 的平移 `(X_i,Y_i)`；
- 是否先沿 y 轴反射 `F_i`；
- 再旋转 `R_i` 次 90°；
- 用 shelf、skyline、bin packing、局部搜索等策略降低最终面积。

Agent 可以根据 checker 的合法性和 partial score 继续优化，但不能读取隐藏解或改 judge。

### 期待输出是什么

标准输出格式为：

```text
W H
X_1 Y_1 R_1 F_1
X_2 Y_2 R_2 F_2
...
X_n Y_n R_n F_n
```

变换后的所有格子必须落在 `W×H` 矩形中，任意两块不能占用同一格。

### Verifier 如何评分

Checker 先验证输出行数、变换、边界与无重叠。合法时计算：

```text
ratio = 所有 polyomino 单元格总数 / (W × H)
```

填充率越高越好。上游 server 把 checker ratio 映射成百分制；本机 reference run 得到 `checker_ratio=0.93089935`、`score=93.089935`。

需要特别处理一个语义陷阱：上游 JS 对非满分解仍可能返回 `passed=false / Wrong Answer`，即使 placement 完全合法且有高 partial score。当前 adapter 绕过 server 的布尔映射，直接编译并调用未修改的官方 checker，解析 `Ratio:`；不能把该 partial score 误解析成 0 分。

上游 reference 还用 wall clock 作为随机种子，并用时间预算停止搜索。因此同一源码多次运行会有轻微波动：本机 seed-smoke 约为 `92.83-93.09`。正式对比必须对 final score 做重复测量，或要求候选使用固定随机种子；单次 reference 分数只证明 judge 接线。

通用 Plain Codex runner 的首个 host-capable smoke 使用 `gpt-5.6-sol/high`、`T=180s`、`K=2`，两个 lane 都能在计时内直接调用 Docker-backed `evaluate.py`；最终选择的合法候选为 `93.4561753`，总计记录 12 次 evaluator calls。因为 reference 与候选都含 clock-seeded 搜索，这个小幅差异不能直接解释为稳定方法收益。

Goal Plus 的 host-capable smoke 使用同一模型、`T=420s`、`K=2`：2 个 candidate 都绑定到真实 Codex session 并提交 verifier，累计 7 次 process iterations；durable search best 为 `93.3980341`，promotion gate 重测为 `93.2217282`，独立 final evaluator 再测为 `93.3097979`，总计记录 10 次 evaluator command/call。这三个不同值正好暴露了 clock-seeded 噪声；接线成立，但正式实验必须改为多次 final 测量或固定 RNG。

---

## 实验怎么用

当前 Mac 已能运行 problem 0 的 1.27 GB judge image。通用 adapter 使用一个 `--network none`、2 CPU、2 GiB 的持久 compile/check 容器，不依赖上游 HTTP server 或 `--privileged`。接下来应：

Codex 需要访问 host Docker socket；runner 因此只对本题与 ALE 显式使用 `danger-full-access`，其余 standalone cases 仍是 `workspace-write`。若误用 workspace sandbox，agent 内部会把不可访问的已安装镜像误报成 missing image；这种 run 只能保留为诊断，不能进入主表。

1. 建立 plain Codex 的通用 C++ 候选与 raw-score parser；
2. 从公开 Pass@1/分数分布选 5 个容易、5 个困难但有 gradient 的题；
3. 先用 1–3 次调用确认 10 题 environment/evaluator；
4. 再用 20-call matched budget 比较 search strategy；
5. Research/GPU 任务迁到 Linux，不在当前 Mac 强行覆盖。

188 题只扫 reference/verifier 约 1–3 小时。若给每题一个最低 180 秒 agent turn，理论下限已约 9.4 小时；实际单次全覆盖约 10–30 小时，20 calls/题则可能达到 100–300 小时。

## 可复用对比数据

- 官方 problem statement、testdata、solution 和 custom checker 可复用，适合冻结 exact judge。
- 官方结果可帮助按 Pass@1 分层抽样，避免只挑模型永远得 0 的题。
- 跨题汇总前必须确认 score scale 和方向；以 checker-native raw score 为主，不能只看 `passed`。

## 代码与证据

- 上游：[FrontierCS/Frontier-CS](https://github.com/FrontierCS/Frontier-CS)
- 本机 judge 结果：[`evidence/environment/2026-07-21-mac-representative-smokes.json`](../../evidence/environment/2026-07-21-mac-representative-smokes.json)
- Plain/Goal Plus 统一入口：[`experiments/benchmark_compare/`](../../experiments/benchmark_compare/)
- Standalone E2E 汇总：[`evidence/runs/2026-07-23-standalone-benchmark-codex-goal-plus.md`](../../evidence/runs/2026-07-23-standalone-benchmark-codex-goal-plus.md)
- 镜像空间规划：[`docs/docker-storage-plan.md`](../docker-storage-plan.md)

[上一篇：SwarmResearch](swarmresearch-15.md) | [返回 Benchmark 导读](README.md)

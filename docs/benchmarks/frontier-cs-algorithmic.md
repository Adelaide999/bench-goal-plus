# Frontier-CS Algorithmic

## 30 秒理解

Frontier-CS 把开放式计算机科学问题封装成可执行 judge。Algorithmic track 不是传统“写出正确算法就满分”：许多题允许合法的近似解，并按解质量给连续 partial score，因此 agent 可以在多轮反馈中持续改进程序。

| 项目 | 内容 |
|---|---|
| 当前固定 Algorithmic track | 188 题 |
| 本项目本机范围 | 先 materialize problem 0，再选 5 个高 Pass@1 + 5 个低 Pass@1 |
| 候选 artifact | 读取任意实例的可编译程序，通常为 C++ |
| 指标 | checker-native partial score；每题方向由 statement/checker 定义 |
| 当前门禁 | problem 0 judge image、reference solution 和 partial-score parser 已通 |
| 固定源码 | `FrontierCS/Frontier-CS@07500f9` |

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

需要特别处理一个语义陷阱：上游 JS 对非满分解仍可能返回 `passed=false / Wrong Answer`，即使 placement 完全合法且有高 partial score。Goal Plus adapter 必须读取 checker message 和 raw score，不能把这个布尔值误解析成 0 分。

---

## 实验怎么用

当前 Mac 已能运行 problem 0 的 1.27 GB judge image，使用 `--privileged --shm-size=4g` 和单 worker。接下来应：

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
- 镜像空间规划：[`docs/docker-storage-plan.md`](../docker-storage-plan.md)

[上一篇：SwarmResearch](swarmresearch-15.md) | [返回 Benchmark 导读](README.md)

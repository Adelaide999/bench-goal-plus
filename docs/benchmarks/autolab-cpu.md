# AutoLab CPU subset

## 30 秒理解

AutoLab 把长期自主研究变成可执行任务：agent 进入一个已经能运行的工程环境，在数小时预算内读说明、修改 artifact、反复做实验并保留最好版本。完整集合有 36 题；本项目先取不要求 GPU 的 25 题，避免把硬件可用性误当成 agent 能力。

| 项目 | 内容 |
|---|---|
| 完整 benchmark | 36 题，覆盖 systems、编译、ML、优化和研究型任务 |
| 本项目范围 | `task.toml` 中 `gpus = 0` 的 25 个 CPU 任务 |
| 候选 artifact | task-specific 源码、配置或实验产物 |
| 指标 | correctness gate + task-native 连续 reward |
| 资源上限 | 单任务最多 4 CPU、4096 MiB；20 题为 2h、5 题为 4h agent budget |
| Docker | **混合**；当前 `toy_isa_opt` host adapter 不需要，完整 Harbor/task 路径需要容器 |
| 无 Docker 环境 | 可以跑 `toy_isa_opt`；不能据此复现完整 25-task CPU subset |
| 当前门禁 | `toy_isa_opt` 的 host evaluator、Plain Codex 和 Goal Plus + Codex 已通 |
| 固定源码 | `MetaStone-AI/AutoLab@7aff5fe` |

它真正测试的是长时 agent 的实验纪律：能否先建立正确 baseline，形成假设，执行可证伪实验，避免 hardcode/改 verifier，并在多次尝试后留下 best-seen artifact。

---

## 代表 case：Toy ISA Optimization

任务模拟一颗简单顺序处理器。程序计算两个长度为 512 的整数数组点积；结果必须完全正确，同时要通过指令调度、循环展开和地址计算优化降低模拟 cycles。

### 输入是什么

上游正式路径把任务放进容器；本项目当前的 host-portable adapter 会把等价的
固定源码复制到仓内临时 build 目录。Agent 看到的任务边界是：

- 可编辑文件：`program.s`；
- 只读参考：`main.c`、`Makefile` 和任务说明；
- 隐式数据：A 位于 word address `0..511`，B 位于 `512..1023`，元素范围为 `[0,996]`；
- 最终结果：程序 halt 时寄存器 `r1` 必须等于点积。

基线汇编的核心循环是：

```asm
loop:
  ld   r6, 0(r4)
  ld   r7, 0(r5)
  mul  r8, r6, r7
  add  r1, r1, r8
  addi r4, r4, 1
  addi r5, r5, 1
  addi r2, r2, 1
  bne  r2, r3, loop
halt
```

模拟器一次发射一条指令，并因数据依赖停顿；`add/addi` 延迟 1 cycle，`ld` 为 5，`mul` 为 5，`mac` 为 6，taken branch 另加 2。

### Agent 要做什么

Agent 只能修改 `program.s`，并反复运行官方测试。可探索方向包括：

- 用 `mac` 合并乘加；
- 展开循环，摊薄 branch 和 counter 开销；
- 交错多个独立 load/multiply chain，隐藏依赖延迟；
- 减少地址与循环控制指令；
- 在多个 seed 上确认优化没有依赖固定输入。

禁止修改 `Makefile` 或 simulator，也不能把某个测试 seed 的结果硬编码到 `r1`。

### 期待输出是什么

最终产物是优化后的 `program.s`，而不是一段自然语言答案。汇编必须使用任务 ISA、最终执行到 `halt`，并把正确点积留在 `r1`。

测试程序的机器可读输出类似：

```text
cycles=2194 verify=ok
```

其中 `verify=ok` 是硬门槛，`cycles` 越低越好。

### Verifier 如何评分

Verifier 会构建 simulator，先跑 seed `0`，再用 `42/137/999` 复查正确性和 hardcode。任一 seed 错误、超时或受保护文件被修改都得到 0 reward。

通过后按 cycles 线性归一化：基线 `9220` 对应 0，verifier 当前使用的 best-known `1545` 对应 1，并截断到 `[0,1]`。任务 metadata 中另有 reference `2954`；正式实验应保存这两个原始字段，不能把 metadata reference 当成 verifier 的归一化常量。

本机 seed 得到 `cycles=9220, verify=ok`；历史优化证据达到 `cycles=2194, reward=0.9154`。新的 host-portable runner 用 `gpt-5.6-sol/high`、`K=2` 跑出 Plain Codex `1547 cycles`；Goal Plus 在 `T=360s` 内确实启动 2 个 Codex lineage、其中 1 个提交 verifier，但本轮最终仍是 seed `9220`。这只能证明接线成立，不能把单轮结果解释为方法排名。

---

## 实验怎么用

先用这题验证 Goal Plus 的长时闭环，而不是立刻跑满 25 题：

1. plain Codex 与 Goal Plus 都从相同 `program.s` 开始；
2. controller 记录每次测试、cycles、candidate hash 和 parent；
3. 先给 10 分钟 bounded budget，确认不会回退或污染 verifier；
4. 再扩大到 1–2 小时，比较 best-seen curve、有效实验率和最终 cycles；
5. 成功后选 6–10 个 CPU 任务做正式 hard subset。

25 题完整原始 agent budget 合计 60 小时；单 worker 加上构建和 verifier，约需 2.5–3 天，因此更适合 Linux campaign，不适合作为 Mac 上的日常回归。

## 可复用对比数据

- 每题都带任务说明、容器资源、测试脚本和 reward 计算，可直接复评分。
- 论文/仓库中的参考 reward 可做 sanity check，但长时 agent 的运行环境、模型和总预算必须同时报告。
- AutoLab 各题 reward 含义不同；跨题汇总可用 normalized reward，报告中仍要保留 cycles、accuracy、runtime 等原始指标。

## 代码与证据

- 上游：[MetaStone-AI/AutoLab](https://github.com/MetaStone-AI/AutoLab)
- 历史 smoke：[`evidence/legacy-smokes/autolab-toy-isa-reward.json`](../../evidence/legacy-smokes/autolab-toy-isa-reward.json)
- Plain/Goal Plus 统一入口：[`experiments/benchmark_compare/`](../../experiments/benchmark_compare/)
- Standalone E2E 汇总：[`evidence/runs/2026-07-23-standalone-benchmark-codex-goal-plus.md`](../../evidence/runs/2026-07-23-standalone-benchmark-codex-goal-plus.md)
- 镜像与本机结果：[`evidence/environment/2026-07-21-mac-representative-smokes.json`](../../evidence/environment/2026-07-21-mac-representative-smokes.json)

[上一篇：Frontier-Engineering](frontier-engineering-v1-lite.md) | [返回 Benchmark 导读](README.md) | [下一篇：SwarmResearch](swarmresearch-15.md)

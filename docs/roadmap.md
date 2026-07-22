# Benchmark integration roadmap

## 目标 claim

固定模型、任务初始状态、官方 evaluator、总 wall budget `T` 和并发 `K` 时，Goal Plus + Codex 相比 plain Codex、固定并行 lineages 与进化搜索 baseline，获得更高的 deadline best / best-seen AUC；实际 tokens、验证次数、成本与 host 同时报告，提升不能只由更多 compute 解释。

## 全局工作分解

### P0：控制面与证据格式

- [x] 建立中央仓库、状态 registry 与 fork/upstream/commit 映射。
- [x] 建立非交互 Codex runner，保留 JSONL、thread id、usage、stderr、最终消息和 manifest。
- [x] 为 6 套 active benchmark 建立统一导读，记录规模、时间与代表 case 的 I/O/verifier 契约。
- [x] 定义 Goal Plus 的逐 benchmark 接入改造、三层并发、matched-budget baseline 与非 Pass@K 验收协议。
- [ ] 定义统一 benchmark adapter 接口：`materialize -> prompt -> evaluate -> parse -> archive`。
- [x] OpenEvolve example adapter 支持原子 evaluator ledger；显式 hard cap 只用于 mechanism ablation，系统级主实验按 outer wall deadline 运行。
- [ ] 将 Codex ST controller 产品化为 batch runner，计入 main-agent 与 worker usage。
- [x] 为 OpenEvolve examples 实现 catalog/materialize/evaluate/archive adapter、原子 evaluator ticket 和 Plain Codex Function Minimization smoke。
- [x] 实现相同 task/evaluator、`T/K` 外层控制的 OpenEvolve native / Plain Codex / Goal Plus runner；真实 native 与 Goal Plus 模型 run 尚待验收，OpenEvolve 内部不增加 Codex provider。
- [x] 固定 OpenEvolve/Goal Plus commit 与 Python lock，提供 fresh-host bootstrap/doctor 和 run-local Goal Plus workspace。
- [ ] 为 OpenEvolve 原生 OpenAI-compatible 路径增加 usage/cost instrumentation。
- [ ] 定义统一 run manifest 扩展：task commit、image digest、model/provider、seed、预算和网络策略。
- [ ] 定义 evaluator-call ledger；不能用“iteration”代替真实验证次数。

### P1：ALE-Bench Lite

完成定义：

- [ ] fork 上建立 `integration/codex` 分支，保留 upstream remote。
- [x] `ahc027` materializer 只暴露题目和可编辑 C++ artifact；private-lite 不进入 workspace。
- [x] controller 独立调用 public evaluator，候选不能读 private-lite。
- [x] plain Codex 1 turn 产生可编译候选；JSONL usage 和 evaluator payload 落盘（2026-07-21，5/5 AC，raw score 改善 9.99%）。
- [ ] Goal Plus + Codex 至少 2 lineages / 3 evaluator calls，父子关系和 best-seen 可回放。
- [ ] 扩到 Lite 10 后再比较 random / evolve / parallel；private-lite 只做最终评分。

### P2：HeuriGym

完成定义：

- [ ] 把当前 macOS `taskset` fallback 和匿名数据下载改动审阅后提交到 fork。
- [ ] `operator_scheduling` 独立 workspace + 固定 demo/eval 边界。
- [ ] plain Codex 生成 solver，官方 `verify()` 与 cost 均落盘。
- [ ] Goal Plus 接 feedback 后能修复至少一种语法/运行/无效解失败。
- [ ] 先覆盖 7 个轻任务，再补 `global_routing`、`intra_op_parallel`。

### P3：Frontier-Engineering v1-lite

完成定义：

- [x] sparse checkout `ComputerSystems/MallocLab`，在 Mac 原生运行官方 verifier；确认 v1-lite 本身不要求 Docker，并记录 raw 28/100、6/11 cases。
- [ ] 冻结 raw score parser；不先做跨任务归一化。
- [ ] plain Codex 与 Goal Plus + Codex 都通过同一个只读 verifier。
- [ ] 20–30 evaluator calls 做策略筛选；只让前两名进入官方 100 calls × 3 seeds。

### P4：AutoLab CPU subset

完成定义：

- [ ] 为 `toy_isa_opt` 增加 Codex agent 配置，不运行 NVIDIA-only `harbor_patch.sh`。
- [ ] plain Codex 在 Harbor task container 中完成一次 artifact 修改和 official reward。
- [ ] Goal Plus 的控制状态不进入候选 workspace / verifier bundle。
- [ ] 扩到 4 个 puzzle，再决定 6-task CPU hard subset。

### P5：SwarmResearch final substrate

完成定义：

- [ ] 修复复现仓 package/import/bootstrap，冻结完整 15-task 依赖和 evaluator image digest。
- [x] Math `circle_packing` 的 evaluator-only 与论文式 task image 均构建，官方 evaluator score 0.9597642169962064。
- [ ] ADRS `eplb`、ALE `ahc015` 各跑通一次 `task-eval`；先补齐上游缺失的共享 worker build context。
- [ ] 建立 `optimization score -> task-native metric -> paper metric` 映射。
- [ ] plain Codex、Goal Plus + Codex、fixed parallel 与 EvoX 使用统一 evaluator-call ledger。
- [ ] 5-task pilot 后才进入 15 tasks × methods × seeds 最终实验。

### P6：Frontier-CS

完成定义：

- [x] sparse checkout `algorithmic/problem-0`，固定 Node/npm/go-judge，构建 1.27 GB judge image 并获得 raw score 93.089935。
- [ ] 建立 plain Codex smoke，并显式处理“有效部分分数仍被上游标为 Wrong Answer”的语义。
- [ ] 再选择 5 high/5 low Pass@1 子集。
- [ ] systems/GPU tasks 转移到 Linux 32 GB+ / GPU 节点，不在当前 Mac 强行 campaign。

### P7：PERFOPT-Bench

完成定义：

- [ ] 恢复可执行 artifact 并确认授权、commit 与 12-task 版本。
- [ ] correctness、重复 timing、环境 fingerprint 与 shortcut audit 作为一等证据。
- [ ] raw speedup 不能直接做 champion promotion。

## 每个阶段必须报告

- 原始 task metric、优化方向、有效性和 best-seen 曲线
- evaluator/model calls、input/output/cached/reasoning tokens、wall-clock、已知费用
- 候选 artifact hash、parent id、diff、verifier payload、失败类别
- model/provider、Codex version、Goal Plus commit、benchmark commit、镜像 digest
- 是否允许网络、是否可读 evaluator、public/private 数据边界

# 通用 Benchmark 支持与 Goal Plus 消融边界

本文把场景选型文档和实现指令映射到 `bench-goal-plus` 的真实代码边界。结论是：
重型 benchmark、Codex 启动和部署期监控继续由本仓控制；Goal Plus core 只提供
搜索运行时，不再在 core 内维护第二套 campaign 系统。

## 可直接复用

| 需求 | 现有实现 | 复用方式 |
|---|---|---|
| 上游版本冻结 | `benchmarks/registry.json`、`environment/upstreams.json` | 跟踪明确 branch；每个 cell manifest 记录 resolved commit |
| Codex 启动和证据 | `scripts/run_codex.py`、standalone runner | 保存 JSONL、stderr、thread/usage、deadline 和 final artifact |
| 隔离 Environment Lane | 各 `adapters/*/adapter.py` | 每条 Plain lane 一个 Git workspace；Goal Plus 每个 candidate 一个 workspace |
| parent-owned evaluator | adapter 的 `evaluate_workspace` 和 Goal Plus promotion verifier | worker 自报分数不作为最终结果，final 由 controller 再跑 |
| 长期并发 | Plain 的 K 个进程、Goal Plus `parallel_loops` | 固定 live `K`，不按 candidate 无限扩环境 |
| 部署生命周期监控 | standalone manifest；EdgeBench `prepare/run/status/stop/finalize` | 通用 campaign 读取同一 cell manifest；原生 harness 仍保留自己的完整 lifecycle |
| 原始指标和方向 | `primary_metric`、`direction`、evaluator history | 汇总只新增 directional gain/AUC，不替换 native metric |

## 本次补齐

1. `benchmarks/task-adapters.json` 与 `adapters/registry.py` 把 standalone adapter
   从 runner 内的硬编码字典变成可校验契约。新增 artifact 型任务只需实现
   materialize/evaluate/metadata contract 并登记模块。
2. standalone runner 的 manifest 现在冻结 B0-B4 条件语义、adapter contract、
   Search Space mode 和 coordination reviewer 配置。
3. `experiments/benchmark_campaign/experiment.py` 展开
   `benchmark x condition x seed`，逐 cell 复用现有 prepare/run，持续写
   campaign 状态，重复执行时跳过 terminal cell。
4. 汇总同时输出两种成本视图：实际 evaluator calls/tokens，以及每 cell 的
   wall time/live concurrency。缺失 telemetry 保持 `n/a` 和 coverage，不能记成 0。
5. 从 evaluator history 计算 best-score trace、directional-improvement AUC、
   threshold 的时间/调用数；从 Search Space 文件计算 reviewer 判重、实际 reject、
   Evidence 跨 lineage 引用和 footprint overlap。

## 条件映射

| 条件 | 控制面实现 | 运行时事实 |
|---|---|---|
| B0 Single Loop | `plain-codex,K=1` | 单独 workspace，无共享 |
| B1 Independent Parallel | `plain-codex,K>=2` | K 个互不共享的 workspace/run，deadline 后统一选 best |
| B2 Shared Final Only | 不支持，CLI 明确拒绝 | `get_agent_context` 没有“只暴露 final/best”的 history filter |
| B3 Shared Evidence, No Admission | `goal-plus-codex` + `search_space mode=observe` | 计划、review 和 Evidence 落盘；review reject 不阻止执行 |
| B4 Full Goal Plus | `goal-plus-codex` + `search_space mode=enforce` | 计划可见、reject/reserve、Evidence、verifier linkage 和 lineage continuation |

way 对应关系不是另一个可任意相乘的假标签：`way1` 是 B4 的 `enforce`，
`way2` 是 B3 的 `observe`。`way0` 要求“计划不可见、Evidence 不更新但仍 reject”，
当前 runtime 没有这组三维开关，因此和 B2 一样显式拒绝。只有实际创建了冻结 mode
的 Search Space，B3/B4 cell 才能成为 `finished`。

## 调用链

```text
benchmark_campaign prepare
  -> adapter registry 校验任务模块
  -> benchmark_compare prepare
  -> adapter materialize 隔离 workspace + 冻结 evaluator/task/commit
  -> experiment.json (prepared)

benchmark_campaign run
  -> benchmark_compare run
  -> B0/B1: 启动 1/K 个 Codex lane
  -> B3/B4: 启动 Goal Plus 总控 Codex
       -> 自然 intake/triage/freeze/create_run
       -> search_space_open(observe/enforce)
       -> K 个长期 Codex candidate lineage
       -> AtomicPlan -> edit -> process verifier -> Evidence -> continue
       -> select -> parent promotion verifier
  -> controller final evaluator
  -> experiment.json (finished/incomplete)
  -> campaign-summary.json/.md
```

campaign 控制器本身不启动 worker、不分配 candidate，也不实现 benchmark-specific
停止条件。它启动已有 runner 并监控持久化状态；Codex/Goal Plus/SForge 继续拥有各自
进程和 closeout 语义。

## 数据集已登记，执行适配仍需增加

当前公共 adapter contract 适合“一个主要可编辑 artifact + controller evaluator”的
任务。`benchmarks/datasets.json` 已登记 WebArena/WorkArena、SWE-EVO、Cybench、
CyberGym、RoadmapBench 与审慎使用的 SWE-bench panels，但目录项不代表 E2E ready。
这些任务不能被硬塞进 standalone artifact 形态，后续应各自接入：

- 固定数量、可 reset/replay 的 service/container Environment Lane；
- benchmark-native task materializer、observer 和 final judge；
- 与本 campaign 相同的 cell manifest/status/summary contract；
- 浏览器 action、patch/test、probe/flag 各自的 partial-progress 与重复行为指标。

推荐顺序仍是：先用 `local-vliw` 或现有 CPU task 做 B0/B1/B3/B4 shakedown；随后接
WebArena/WorkArena L1 做低成本机制验证；再接 SWE-EVO development panel；最后才是
CyberGym 固定 panel 和 EdgeBench 长时任务。B2/way0 应先在 Goal Plus runtime 增加
可测试的 visibility/evidence policy，不能只靠 prompt 假装隔离。

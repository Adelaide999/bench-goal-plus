# Goal Plus Agent Comparison Experiment Plan

## 1. Purpose

当前 bench-goal-plus 已经逐步形成 benchmark adapter、campaign control plane 和 evidence 记录能力。
下一阶段重点不是继续增加 benchmark 数量，而是在相同 benchmark、相同 evaluator 条件下，对比不同 Agent/Search 方法。

核心目标：

> 建立一个统一实验协议，让 Goal Plus 可以与其他 Agent harness/search algorithm 公平比较。

实验对象包括：

- Goal Plus
- Vanilla autoresearch loop
- SwarmResearch
- EvoX
- CORAL
- OpenEvolve
- AdaEvolve
- GEPA/ShinkaEvolve（扩展）

---

# 2. 实验基本原则

## 2.1 Benchmark 与 Agent 分离

不要把 benchmark 和 agent 混在一起。

Benchmark 提供：

```text
Task
Baseline artifact
Evaluator
Metric definition
Environment
Resource requirement
```

Agent 提供：

```text
Search strategy
Agent orchestration
Memory/state handling
Candidate management
Iteration policy
```

统一流程：

```text
              Same Benchmark
                    |
       +------------+------------+
       |            |            |
 Goal Plus   SwarmResearch    EvoX
       |            |            |
       +------------+------------+
                    |
          Parent-owned Evaluator
                    |
             Comparable Result
```

---

# 3. Agent Runner Architecture

建议增加统一 runner 概念：

```text
agent_runners/

    goal_plus/

    swarmresearch/

    evox/

    openevolve/

    baselines/
        vanilla_loop/
```

每个 runner 负责：

- 初始化 agent
- 管理 agent lifecycle
- 收集 trajectory
- 输出统一 result format

不负责：

- benchmark-specific evaluator
- 修改 score 定义
- 自己维护最终排名

---

# 4. 统一 Task Contract

所有 benchmark adapter 输出统一接口。

## Task Manifest

```yaml
name:
baseline:
workspace:
evaluator:
metric:
metric_direction:
resource:
time_budget:
```

## Evaluator Contract

Evaluator 必须返回：

```json
{
  "valid": true,
  "score": 123.4,
  "metrics": {},
  "runtime": {},
  "errors": []
}
```

最终 best 必须由 evaluator 决定。

禁止：

- Agent 自报 score
- commit message 作为结果
- findings.md 作为官方结果

---

# 5. Agent 对比对象

## 5.1 Vanilla autoresearch

用途：最低级 baseline。

回答：

> 增加更长运行时间是否本身可以带来提升？

特点：

- 单 Agent
- 单 workspace
- 无显式 population
- 无跨 Agent 协调

---

## 5.2 Goal Plus

当前方法。

核心：

- initial candidates
- candidate owns autonomous loop
- main 负责启动、验收、resume
- 不持续作为 search conductor

未来扩展：

- Search Evidence
- Search Schema
- AtomicPlan
- EvidenceCommit

---

## 5.3 SwarmResearch

代表：中央 orchestrator 多 Agent。

结构：

```text
Shepherd
   |
 +------+------+
Explorer Optimizer
```

特点：

- 动态创建 Agent
- Git branch/worktree population
- Shepherd 决定 parent 和方向

实验价值：

比较：

> centralized orchestration vs autonomous candidate loop

---

## 5.4 EvoX / SkyDiscover algorithms

代表：algorithm-guided search。

特点：

- population
- evolution
- mutation
- search strategy adaptation

实验价值：

比较：

> explicit search algorithm vs agent-owned search loop

---

## 5.5 CORAL

代表：自治多 Agent 协作。

实验价值：

比较：

> shared agent collaboration vs structured runtime coordination

---

# 6. Benchmark 选择策略

不要所有 Agent 跑所有 benchmark。

分两条 track。

---

# Track A: Search Algorithm Benchmark

目标：比较搜索策略。

推荐：

- ALE-Bench
- HeuriGym
- Frontier-CS
- SkyDiscover tasks
- OpenEvolve examples

适合比较：

```text
Goal Plus
Vanilla
SwarmResearch
EvoX
OpenEvolve
AdaEvolve
```

关注：

- exploration
- diversity
- stagnation recovery
- best score curve

---

# Track B: Long Horizon Engineering

目标：比较真实工程优化能力。

推荐：

- EdgeBench
- AutoLab
- Frontier-Engineering
- future GSO
- FormulaCode

主要比较：

```text
Goal Plus
Vanilla
SwarmResearch
CORAL
```

原因：

这些任务需要：

- repository understanding
- profiling
- multi-file modification
- debugging
- long workspace continuity

---

# 7. 公平预算协议

不能只限制 iteration。

必须记录：

## Model budget

- input tokens
- output tokens
- reasoning tokens（如果可获得）

## Execution budget

- wall clock
- evaluator calls
- CPU/GPU time

## Agent budget

- maximum concurrent agents
- maximum branches/candidates

## Cost

- API cost
- subscription equivalent cost

---

# 8. Result Metrics

不能只看 final score。

## Performance

- final verified score
- best score
- best score AUC
- improvement over baseline

## Search efficiency

- score improvement / token
- score improvement / evaluator call
- score improvement / time

## Search behavior

- number of attempts
- valid attempt ratio
- candidate diversity
- repeated exploration rate
- stagnation recovery

## Engineering quality

- correctness pass rate
- crash rate
- environment failure
- reproducibility

---

# 9. Experiment Matrix

第一版建议：

| Agent | Track A | Track B |
|-|-|-|
| Vanilla | yes | yes |
| Goal Plus | yes | yes |
| SwarmResearch | yes | yes |
| EvoX | yes | optional |
| OpenEvolve | yes | optional |
| CORAL | optional | yes |
| AdaEvolve | yes | optional |

---

# 10. Implementation Order

## Phase 1

完成统一 result schema：

- score
- metrics
- trajectory
- cost
- resource

## Phase 2

接入 baseline agents：

1. Vanilla
2. SwarmResearch
3. EvoX

## Phase 3

接入复杂 agent：

- CORAL
- OpenEvolve
- AdaEvolve

## Phase 4

真实工程 benchmark：

- EdgeBench
- GSO
- FormulaCode

---

# 11. 最终实验目标

最终不是证明某个 Agent 永远最好。

而是回答：

1. 单 Agent scaling 是否有效？
2. 中央 Agent orchestration 是否优于自治 loop？
3. Evolutionary search 是否适合开放式工程优化？
4. 结构化 Search State 是否减少重复探索？
5. 长时间搜索中，什么样的状态表示最有效？

Goal Plus 的核心贡献应通过统一实验框架体现，而不是通过单个 benchmark 的最高分体现。

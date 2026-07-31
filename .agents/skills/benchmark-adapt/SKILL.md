---
name: benchmark-adapt
description: 把新 benchmark 或新 task family 接入 bench-goal-plus。用户要求快速适配 benchmark、登记上游 fork/branch、实现 materialize/evaluate adapter、复用 native harness、定义并发标准、增加 install/run/report 支持或完成接入验收时使用。
---

# 新 Benchmark 适配

完整执行 [adaptation-checklist.md](references/adaptation-checklist.md)。先判断 benchmark 是否适合 common artifact adapter；native harness 已拥有容器、服务、浏览器、调度或 hidden judge 时保留 native lifecycle，只接控制面契约。

## 流程

1. 记录 official task、artifact、evaluator、raw metric、direction、环境、数据 revision、license 和 secret 边界。
2. 在独立 fork 建 benchmark-specific 改动；同时在 `benchmarks/registry.json` 与 `environment/upstreams.json` 登记同一显式 tracking branch。
3. 声明 readiness 的 `docker_requirement`/`docker_scope`，并在 `benchmarks/runners.json` 声明 Docker `owner`/`provision_mode`。自带 Docker/native harness 用 runner owner；common adapter 选择 eager hooks 或 lazy evaluator。
4. 选择接入面：单 artifact + controller evaluator 使用 `adapters/` contract；复杂 native harness 增加 `experiments/<benchmark>/` lifecycle 和一个可复用 runner；不要强塞进不匹配的 adapter。
5. 固定 `T/K/C/R` 语义和资源上限。无法安全迁移并发时先声明 `K=1`，用小任务验证后再开放。
6. 保留 native raw metric；增加 manifest、status、final evidence、telemetry coverage 和统一报告字段。
7. 增加 registry/adapter/lifecycle/report 测试，完成 model-free seed smoke，再做最小真实 E2E。
8. 更新对应 Skill reference，而不是把 benchmark 特例堆进根 `AGENTS.md`。

## 验收

```bash
python3 scripts/status.py --check
python3 -m unittest discover -s tests -v
```

输出 readiness matrix：official verifier、native OpenEvolve、plain Codex、Goal Plus + Codex、Goal Plus + Pi 五项分别为 pass/partial/fail，并逐项链接命令和 evidence。

## Gotchas

- registry 中“存在”不等于 E2E ready；没有实际命令/evidence 只能是 `partial`。
- 不为模仿其他方法 round 数而向 Goal Plus core 加 benchmark-specific stop logic。
- 不预建 Goal Plus goal/spec/search run/candidate；这些必须在计时内从自然 prompt 开始。
- 不用 host-only evaluator 冒充官方容器 score。

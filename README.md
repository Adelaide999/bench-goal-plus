# bench-goal-plus

Goal Plus 的 benchmark 集成与实验控制仓。它把此前散落在 `mythink/agentic-scaling/benchmark-smoke`、各上游 checkout 和研究计划里的状态，收敛成可验证、可逐项推进的工程项目。

**基于 attitude 的 agent 预分析认为：核心关注，必须系统化推进——真正要证明的不是“Codex 能打开这些仓库”，而是同一任务、同一 evaluator、同一预算下，plain Codex 与 Goal Plus + Codex 的搜索轨迹和 best-seen 提升可以复现、计费并公平比较。**

## 当前结果

- 已新建 8 个 GitHub fork（5 个独立 benchmark、SwarmResearch 的 2 个 substrate/method 仓和 SkyDiscover）；OpenEvolve 原先已有 fork，共跟踪 9 个 fork。
- PERFOPT-Bench 当前没有可 fork 的公开可执行 GitHub 仓库，只有 4open.science artifact 与宣传站，因此明确标为 `blocked`，不拿网站仓冒充 benchmark。
- ALE-Bench Lite、HeuriGym、AutoLab 已有本机官方 verifier / 远端模型 smoke 证据。
- ALE-Bench Lite `ahc027` 已完成首个真实 plain Codex smoke：`gpt-5.4-mini` 改写候选后 5/5 public-lite cases accepted，raw score 从 61,302,533 降到 55,181,186（该题越低越好，改善 9.99%）。
- SkyDiscover/EvoX 已完成 DeepSeek OpenAI-compatible 的 1 iteration smoke，但还不是论文可比实验。
- Goal Plus + Codex 与其余 benchmark 的 plain Codex 尚未验收；这是本仓接下来逐项完成的主线。

## 固定验收门禁

每个 benchmark 按同一顺序推进：

1. `source_forked`：上游、fork、commit 与许可边界已记录。
2. `environment`：依赖与任务数据可重复安装。
3. `official_verifier`：不依赖模型的确定性 baseline 能被官方 evaluator 接受。
4. `legacy_agent_smoke`：上游原生 agent/API 路径至少跑通一例，用于隔离环境问题。
5. `plain_codex`：Codex 在独立 workspace 中改 artifact，controller 能保存 JSONL、usage 和最终文件。
6. `goal_plus_codex`：Goal Plus 驱动 Codex lineage，候选、父子关系、验证与恢复状态可回放。
7. `matched_baseline`：plain / random / parallel / evolve / Goal Plus 使用相同模型、任务、evaluator-call 预算。
8. `campaign_ready`：subset、seeds、资源、反作弊与汇总协议冻结。

任何阶段都不能由“代码里看起来支持”直接跳成 `pass`。

## 范围与顺序

主顺序保持为：

1. ALE-Bench Lite
2. HeuriGym
3. Frontier-Engineering v1-lite
4. AutoLab CPU subset
5. SwarmResearch 15-task substrate（先 Math / ADRS / ALE 各一题）
6. Frontier-CS
7. PERFOPT-Bench（等待公开 artifact 恢复）

SkyDiscover/EvoX 与 OpenEvolve 是 search backend，不与 benchmark 混为一类。EdgeBench 已按用户要求排除。

## 仓库结构

```text
benchmarks/registry.json       唯一状态源：上游、fork、commit、门禁、证据、下一步
docs/roadmap.md                分 benchmark 的推进计划与完成定义
docs/codex-run-contract.md     所有 benchmark 共用的 Codex 执行/证据契约
scripts/run_codex.py           通用非交互 Codex runner，保存 JSONL、usage 与 manifest
scripts/status.py              校验 registry 并打印状态矩阵
evidence/legacy-smokes/        迁入的已验证 smoke 摘要和小型结果
legacy/direct-api/             原有 direct-API smoke 辅助脚本，作为环境基线
tests/                         不调用真实模型的 runner/registry 测试
```

上游仓库不作为 submodule 纳入；后续需要修改 fork 时，在 `.worktrees/` 创建干净工作区，并把 fork commit 回填到 registry。

## 使用

```bash
python3 scripts/status.py
python3 scripts/status.py --check
python3 -m unittest discover -s tests -v
```

通用 Codex runner 的最小形态：

```bash
python3 scripts/run_codex.py \
  --workspace /path/to/isolated-task-workspace \
  --prompt-file /path/to/prompt.md \
  --run-dir runs/<benchmark>/<run-id>
```

runner 不保存环境变量值；模型/provider、任务 commit 和 evaluator 仍必须由 benchmark adapter 写入 run manifest 扩展字段。

## 旧资料边界

`mythink/agentic-scaling/benchmark-smoke` 暂时保留为只读历史来源，避免误删尚未纳入父仓的实验。已迁移的摘要见 [legacy smoke 说明](evidence/legacy-smokes/README.md)。后续状态只在本仓更新。

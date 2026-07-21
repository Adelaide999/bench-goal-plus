# Legacy smoke evidence

来源：`mythink/agentic-scaling/benchmark-smoke`，验证时间 2026-07-18；SkyDiscover/EvoX 补充于 2026-07-20。

这里迁入的是小型、无凭据的结果摘要，用来证明环境/verifier 的既有状态；原始 logs、模型生成文件、AutoLab job 与 SkyDiscover checkpoint 仍保留在原路径，不进入中央 Git 仓。

| Target | 已证明 | 未证明 |
|---|---|---|
| ALE-Bench Lite / `ahc027` | 模型 artifact、C++ 编译、public/private official evaluator；有界修正后 205 cases 有效 | plain Codex、Goal Plus、论文可比搜索策略 |
| HeuriGym / `operator_scheduling` | 模型 API 调用和 official verifier；确定性 solver valid/cost=7 | 模型首稿有效性、plain Codex、Goal Plus |
| AutoLab / `toy_isa_opt` | Terminus-2 + DeepSeek + Docker + official reward；cycles 9220 -> 2194 | Codex host 与 matched baseline |
| SkyDiscover/EvoX / `circle_packing` | DeepSeek OpenAI-compatible、1 variation operator、3 candidate attempts、checkpoint 与独立复评分 | strategy hot-swap、token/cost、Swarm adapter、论文可比结果 |

迁移原则：旧目录暂不删除；后续新的 run 只写入本仓 `runs/`（默认 gitignored），小型可审计摘要再进入 `evidence/`。


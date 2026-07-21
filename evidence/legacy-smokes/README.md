# Legacy smoke evidence

来源：`mythink/agentic-scaling/benchmark-smoke`，验证时间 2026-07-18；SkyDiscover/EvoX 补充于 2026-07-20。

这里包含无凭据的结果摘要与用于审计的必要 artifact。SkyDiscover 的完整 checkpoint、两个程序记录、best program 和去除本机路径后的日志已经迁入；大体积、可重新生成的 Docker/build 临时状态不进入 Git。

| Target | 已证明 | 未证明 |
|---|---|---|
| ALE-Bench Lite / `ahc027` | 模型 artifact、C++ 编译、public/private official evaluator；有界修正后 205 cases 有效 | plain Codex、Goal Plus、论文可比搜索策略 |
| HeuriGym / `operator_scheduling` | 模型 API 调用和 official verifier；确定性 solver valid/cost=7 | 模型首稿有效性、plain Codex、Goal Plus |
| AutoLab / `toy_isa_opt` | Terminus-2 + DeepSeek + Docker + official reward；cycles 9220 -> 2194 | Codex host 与 matched baseline |
| SkyDiscover/EvoX / `circle_packing` | DeepSeek OpenAI-compatible、1 variation operator、3 candidate attempts、checkpoint 与独立复评分 | strategy hot-swap、token/cost、Swarm adapter、论文可比结果 |

迁移已经完成，逐文件映射见 `docs/legacy-smoke-migration.md`。旧 `benchmark-smoke` 目录可以删除。后续新的 run 只写入本仓 `runs/`（默认 gitignored），小型可审计证据再进入 `evidence/`。

校验命令：

```bash
python3 scripts/verify_legacy_smokes.py
```

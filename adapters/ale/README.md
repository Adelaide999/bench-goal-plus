# ALE-Bench Lite adapter

第一阶段只处理 `ahc027` plain Codex smoke：

1. 从官方 ALE session 导出公开题面，不复制 private seeds/inputs。
2. 把旧 smoke 的有效 C++ 候选作为 connectivity starter，初始化独立 Git workspace。
3. 用中央 `scripts/run_codex.py` 运行 Codex；Codex 只能编辑 workspace。
4. controller 在 Codex 结束后用官方 `session.public_eval()` 评分并保存摘要。

这个 starter 不是正式公平 baseline。正式策略对比要从同一冻结初始 artifact 开始，并把 private-lite 留到最终提交。

```bash
export DOCKER_HOST="unix://${HOME}/.orbstack/run/docker.sock"

../ALE-Bench/.venv/bin/python adapters/ale/materialize.py \
  --workspace runs/ale-ahc027/workspace \
  --starter-results ../ALE-Bench/.tmp/e2e-smoke/ale-deepseek-v4-flash/ahc027/results/final_results.json

python3 scripts/run_codex.py \
  --workspace runs/ale-ahc027/workspace \
  --prompt-file runs/ale-ahc027/workspace/TASK.md \
  --run-dir runs/ale-ahc027/codex \
  --model gpt-5.4-mini

../ALE-Bench/.venv/bin/python adapters/ale/evaluate.py \
  --workspace runs/ale-ahc027/workspace \
  --output runs/ale-ahc027/public-eval.json
```

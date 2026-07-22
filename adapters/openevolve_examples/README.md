# OpenEvolve example adapter

This adapter reuses OpenEvolve's existing example contract without running Codex inside the OpenEvolve search controller:

```text
initial_program + evaluator + config
  -> native OpenEvolve runner
  -> plain Codex workspace
  -> Goal Plus + Codex workspace
```

The Python environment must contain the pinned OpenEvolve checkout and the task requirements. The first registered task is `function_minimization`; adding another compatible example only requires one catalog entry in `tasks.json`.

## Reproduce the Plain Codex smoke

```bash
python3 scripts/repro_env.py bootstrap

python3 scripts/openevolve_task.py materialize \
  --task-id function_minimization \
  --upstream-root ../openevolve \
  --runtime-python .bench-env/venv/bin/python \
  --workspace /tmp/openevolve-function-minimization \
  --max-evaluator-calls 7 \
  --reserved-final-calls 1

python3 scripts/openevolve_task.py evaluate \
  --workspace /tmp/openevolve-function-minimization \
  --mode public

python3 scripts/run_codex.py \
  --workspace /tmp/openevolve-function-minimization \
  --prompt-file /tmp/openevolve-function-minimization/TASK.md \
  --run-dir evidence/runs/<run-id> \
  --sandbox workspace-write \
  --ephemeral

python3 scripts/openevolve_task.py evaluate \
  --workspace /tmp/openevolve-function-minimization \
  --mode final \
  --output evidence/runs/<run-id>/final-eval.json

python3 scripts/openevolve_task.py archive \
  --workspace /tmp/openevolve-function-minimization \
  --run-dir evidence/runs/<run-id>
```

The materialized workspace exposes `python3 evaluate.py` to the agent. Every invocation atomically claims an evaluator ticket and appends a canonical result to the ignored `.bench-runtime/history.jsonl`. The final controller evaluation uses the reserved `final` ticket. `archive` verifies that the saved candidate matches that final evaluation, copies the canonical trajectory, and removes the local home path from textual Codex evidence.

The evaluator JSON preserves `primary_metric` and all `raw_metrics`, and also emits the finite primary metric as a top-level field (for example `combined_score`) so the same command is a valid Goal Plus ranking verifier. Invalid/non-finite candidates receive a direction-aware finite worst-case ranking value while retaining `valid=false` and the original failure payload.

Omit `--max-evaluator-calls` for the main wall-clock comparison. In that mode public calls are counted but not rejected; `reserved-final-calls` still protects the controller-owned final evaluation. Use an explicit cap only for a separately labeled evaluator-call-matched ablation.

## Verified result

The 2026-07-22 smoke reused OpenEvolve commit `411fb59c` and its native `Config` and `Evaluator` classes. Plain Codex improved `combined_score` from `1.2147685971` to `1.4997641484` (`+23.46%`) with 4 public calls plus 1 controller final call. The Codex turn took 110.44 seconds and reported 200,450 input tokens (169,472 cached), 3,280 output tokens, and 858 reasoning tokens.

This is a wiring result, not a matched OpenEvolve baseline: Function Minimization is a toy task, native OpenEvolve has not yet been run under the same evaluator-ticket budget, and this Codex invocation did not expose an explicit model identity. The canonical evidence is in [`evidence/runs/2026-07-22-openevolve-function-minimization-plain-codex`](../../evidence/runs/2026-07-22-openevolve-function-minimization-plain-codex/summary.json).

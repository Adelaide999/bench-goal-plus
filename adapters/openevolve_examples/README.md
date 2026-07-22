# OpenEvolve example adapter

This adapter reuses OpenEvolve's existing example contract without running Codex inside the OpenEvolve search controller:

```text
initial_program + evaluator + config
  -> native OpenEvolve runner
  -> plain Codex workspace
  -> Goal Plus + Codex workspace
```

The Python environment must contain the pinned OpenEvolve checkout and the task requirements. The `cpu_portable` catalog currently registers 12 examples that use only the Python standard library and the locked NumPy/SciPy environment. They require no GPU, NPU, downloaded dataset, network service, compiler, or external executable.

List the portable batch and run one official seed evaluation for every task:

```bash
.bench-env/venv/bin/python scripts/openevolve_task.py list \
  --task-set cpu_portable

.bench-env/venv/bin/python scripts/openevolve_task.py batch-seed-smoke \
  --task-set cpu_portable \
  --run-root runs/openevolve-batch/<run-id>
```

The batch command creates one isolated workspace per task, evaluates its upstream seed through the controller-owned wrapper, requires a finite primary metric, and writes `summary.json`. It never deletes a prior workspace. The registered set is:

- Function Minimization, Background Blur, Circle Packing with Artifacts, and K-Module;
- Circle Packing Rectangle, Heilbronn Triangle, Kissing Number, and Heilbronn Convex 13;
- Hexagon Packing 11/12 and Minimizing Max-Min Distance 2/3.

Adding another compatible example still requires only one catalog entry in `tasks.json`, but it must declare its execution profile. `cpu_portable` entries are rejected if they declare GPU, NPU, network, downloaded data, or external-software requirements.

## Reproduce the Plain Codex smoke

```bash
python3 scripts/repro_env.py bootstrap

python3 scripts/openevolve_task.py materialize \
  --task-id function_minimization \
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

## Verified results

On 2026-07-22 all 12 `cpu_portable` seeds materialized and returned finite official metrics. Their combined evaluator time was 10.35 seconds; Background Blur was the slowest seed at 9.07 seconds. All 48 task × method cells then prepared successfully; both Goal Plus hosts used the natural `/goal-plus` prompt pipeline with `.gp/` absent at time zero. See the [batch evidence](../../evidence/runs/2026-07-22-openevolve-cpu-portable-batch.md).

The 2026-07-22 smoke reused OpenEvolve commit `411fb59c` and its native `Config` and `Evaluator` classes. Plain Codex improved `combined_score` from `1.2147685971` to `1.4997641484` (`+23.46%`) with 4 public calls plus 1 controller final call. The Codex turn took 110.44 seconds and reported 200,450 input tokens (169,472 cached), 3,280 output tokens, and 858 reasoning tokens.

This is a wiring result, not a matched OpenEvolve baseline: Function Minimization is a toy task, native OpenEvolve has not yet been run under the same evaluator-ticket budget, and this Codex invocation did not expose an explicit model identity. The canonical evidence is in [`evidence/runs/2026-07-22-openevolve-function-minimization-plain-codex`](../../evidence/runs/2026-07-22-openevolve-function-minimization-plain-codex/summary.json).

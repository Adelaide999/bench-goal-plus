# OpenEvolve `cpu_portable` batch evidence

Date: 2026-07-22  
OpenEvolve commit: `411fb59c886c18704caaffb611e17cf9e7d824d2`

## Scope and claim boundary

The catalog was screened for tasks that require no GPU, NPU, downloaded dataset, network service, compiler, or external executable. Task code uses only the Python standard library plus NumPy/SciPy already present in the reproducible environment.

This evidence establishes two claims:

1. all 12 upstream seeds materialize and return a finite primary metric through the controller-owned official evaluator wrapper;
2. all 12 × 4 task/method cells prepare through one campaign command; both Goal Plus hosts use the natural-prompt path with no `.gp` state before the timed invocation.

It does not claim 12 native OpenEvolve searches or 12 paid-model Goal Plus runs. Only `function_minimization` has separate real model E2E evidence.

## Reproduction

```bash
.bench-env/venv/bin/python scripts/openevolve_task.py batch-seed-smoke \
  --task-set cpu_portable \
  --upstream-root third_party/openevolve \
  --runtime-python .bench-env/venv/bin/python \
  --run-root runs/openevolve-batch/<run-id>

.bench-env/venv/bin/python experiments/openevolve_compare/experiment.py prepare-batch \
  --task-set cpu_portable \
  --methods openevolve plain-codex goal-plus-codex goal-plus-pi \
  --run-root runs/openevolve-campaigns/<campaign-id> \
  --wall-time-seconds 300 \
  --concurrency 2 \
  --model gpt-5.6-luna \
  --seed 1
```

## Official seed-evaluator results

All primary metrics are the upstream higher-is-better `combined_score`.

| Task | Seed score | Evaluator seconds |
|---|---:|---:|
| `function_minimization` | 1.2147685971 | 0.018 |
| `background_blur` | 0.9576898127 | 9.070 |
| `circle_packing_with_artifacts` | 0.3642368945 | 0.202 |
| `k_module_problem` | 0.0000000000 | 0.004 |
| `alpha_circle_packing_rect` | 0.0000000000 | 0.008 |
| `alpha_heilbronn_triangle` | 0.0000000000 | 0.007 |
| `alpha_kissing_number` | 0.0033726813 | 0.006 |
| `alpha_heilbronn_convex_13` | 0.0104231038 | 0.009 |
| `alpha_hexagon_packing_11` | 0.4912615000 | 0.012 |
| `alpha_hexagon_packing_12` | 0.4927390375 | 0.013 |
| `alpha_minimizing_max_min_dist_2` | 0.0197911238 | 0.510 |
| `alpha_minimizing_max_min_dist_3` | 0.0179913146 | 0.486 |

Result: 12/12 passed; summed evaluator time 10.346 seconds. The zero-valued seeds were accepted finite upstream results, not wrapper failures.

## Four-path campaign preparation

Result: 48/48 task/method cells prepared: native OpenEvolve, Plain Codex, Goal Plus + Codex, and Goal Plus + Pi for each of the 12 tasks. Every generated `experiment.json` recorded `status=prepared` and `task.execution_profile.class=cpu_portable`. Each Goal Plus cell additionally recorded:

- `prompt_contract.mode=natural_goal_plus_entry`;
- a `GOAL.md` beginning with `/goal-plus mode=autonomous`;
- no workspace `.gp` directory at time zero.

The complete 48-cell prepared campaign occupied 12 MB. The model was not invoked, so preparation had no model-token or API cost.

## Screened-out examples

- `signal_processing`: configured primary metric is absent from evaluator output;
- `claude_code_quickstart`: requires Claude CLI;
- `attention_optimization`: requires compiler/MLIR tooling;
- ARC, SLDbench, and symbolic-regression families: require external datasets;
- TSP: requires C++/Torch tooling;
- JAX/Optax examples: CPU-capable, but outside this zero-extra-environment batch;
- GPU/NPU/MLX and network/credential examples: excluded by definition.

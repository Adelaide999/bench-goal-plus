# OpenEvolve task system comparison

This harness runs one pinned OpenEvolve example through three independent systems while sharing the seed and official evaluator:

- `openevolve`: native OpenEvolve population/island search and OpenAI-compatible API;
- `plain-codex`: one Codex process in an isolated task workspace;
- `goal-plus`: Codex plus pinned Goal Plus project assets in an isolated task workspace.

The primary comparison fixes task/evaluator, total wall-clock budget `T`, and live search concurrency `K`. OpenEvolve receives a deliberately unreachable iteration ceiling and the outer controller sends `SIGTERM` at `T`; Goal Plus receives the same deadline through `GOAL_PLUS_OUTER_DEADLINE_AT`. Evaluator calls, iterations, tokens, and cost coverage are reported after the run rather than hard-capped. Use evaluator-call matching only for separately labeled mechanism ablations.

## Prepare

Run the repository bootstrap first, then create one persistent but Git-ignored run directory:

```bash
.bench-env/venv/bin/python experiments/openevolve_compare/experiment.py prepare \
  --method goal-plus \
  --task-id function_minimization \
  --wall-time-seconds 600 \
  --concurrency 3 \
  --seed 1
```

The command prints `runs/openevolve-compare/<run-id>`. Goal Plus state is confined to `<run-id>/workspace/.gp`; the pinned upstream checkout remains untouched. Run directories are never automatically deleted.

Before spending model budget, verify the evaluator path:

```bash
.bench-env/venv/bin/python experiments/openevolve_compare/experiment.py seed-smoke \
  --run-dir runs/openevolve-compare/<run-id>
```

## Execute

Goal Plus or plain Codex uses existing Codex authentication:

```bash
.bench-env/venv/bin/python experiments/openevolve_compare/experiment.py run \
  --run-dir runs/openevolve-compare/<run-id> \
  --model <codex-model>
```

Native OpenEvolve uses an OpenAI-compatible key only from the environment:

```bash
export OPENAI_API_KEY='<secret>'
.bench-env/venv/bin/python experiments/openevolve_compare/experiment.py run \
  --run-dir runs/openevolve-compare/<run-id> \
  --model <api-model> \
  --api-base https://api.example.com/v1
```

No credential value is written to the run manifest. A hard-killed run is marked `incomplete`, not silently accepted as a comparable result.

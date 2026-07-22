# bench-goal-plus contributor rules

This repository is the control plane for Goal Plus benchmark integrations.

- Keep benchmark upstreams in separate forks. Do not vendor their source or datasets here.
- Pin every upstream/fork commit in `benchmarks/registry.json`.
- Put cross-benchmark orchestration and adapters here; patch a benchmark fork only when the change is intrinsically benchmark-specific.
- Never persist API keys, auth files, cookies, provider headers, or secret-bearing command lines.
- A status can become `pass` only when a reproducible command and evidence file exist. Repository support or an unexecuted code path is at most `partial`.
- Keep five claims separate: official verifier works, native OpenEvolve works, plain Codex works, Goal Plus + Codex works, and Goal Plus + Pi works.
- Preserve raw benchmark metrics and direction. Any normalized aggregate must be an additional field, not a replacement.
- For full-system comparisons, fix the task/evaluator, total wall-clock budget `T`, and live search concurrency `K`. Preserve each method's native control flow; report evaluator calls, iterations, tokens, cost coverage, and actual wall time after the run. Hard-match evaluator calls only in an explicitly labeled mechanism ablation.
- Standard Plain Codex and Codex + Goal Plus comparisons must share one byte-identical common task prompt. Plain Codex uses it directly; Codex + Goal Plus adds only the natural `/goal-plus` prefix and a complete Goal Plus configuration suffix. Do not pre-create Goal Plus goals, frozen specs, Search runs, candidates, or sessions before the timed invocation.
- Never add benchmark-specific stopping logic to Goal Plus core just to mimic another method's rounds. OpenEvolve may use a very large iteration ceiling and an outer `SIGTERM` deadline.
- Never run Goal Plus from an upstream or benchmark source checkout. Materialize a disposable Git workspace under ignored `runs/`; keep its `.gp/` state inside that workspace.
- Do not delete local workspaces or caches automatically. If a conflicting path must be preserved, rename it with a `_bak` suffix and report it.
- Run `python3 scripts/status.py --check` and `python3 -m unittest discover -s tests -v` before committing.

## Fresh-host bootstrap

Host prerequisites are `git`, a Python `3.10+` launcher, `uv`, and Codex CLI `0.144.1+`. Credentials stay in the host environment or Codex auth store; never write them into this repository.

```bash
cd bench-goal-plus
python3 scripts/repro_env.py bootstrap
python3 scripts/repro_env.py doctor
```

`bootstrap` creates the disposable `.bench-env/venv` and clones every pinned
benchmark/search runtime into ignored `third_party/`. It installs editable
OpenEvolve and Goal Plus from that same root, and refuses to rewrite an existing
checkout at another commit. On another machine, recreate `.bench-env` and
`third_party`; do not copy a virtualenv between hosts. To prepare one benchmark
plus the always-required runtimes, use:

```bash
python3 scripts/repro_env.py bootstrap --only heurigym
python3 scripts/repro_env.py doctor --only heurigym
```

Prepare and verify a model-free Goal Plus task workspace. Preparation materializes only the task, evaluator wrapper, and portable Goal Plus host assets; `.gp/` must not exist yet:

```bash
.bench-env/venv/bin/python experiments/openevolve_compare/experiment.py prepare \
  --method goal-plus-codex --task-id function_minimization \
  --wall-time-seconds 300 --concurrency 2 --model gpt-5.6-luna --seed 1

.bench-env/venv/bin/python experiments/openevolve_compare/experiment.py seed-smoke \
  --run-dir runs/openevolve-compare/<run-id>
```

Execute that prepared run with one explicit OpenAI-compatible provider. Keep the key only in the shell:

```bash
export OPENAI_API_KEY='<secret>'
.bench-env/venv/bin/python experiments/openevolve_compare/experiment.py run \
  --run-dir runs/openevolve-compare/<run-id> \
  --model gpt-5.6-luna --api-base https://api.example.com/v1
```

Prepare `openevolve`, `plain-codex`, `goal-plus-codex`, and `goal-plus-pi` separately. Goal Plus intake, triage, SearchSpec freezing, Search-run creation, candidates, and workers all begin from the natural `/goal-plus` prompt inside `T`. See `docs/reproducible-environment.md` for Mac/Linux details and failure semantics.

For the screened no-special-environment OpenEvolve batch, use the catalog instead of preparing tasks by hand:

```bash
.bench-env/venv/bin/python scripts/openevolve_task.py batch-seed-smoke \
  --task-set cpu_portable \
  --run-root runs/openevolve-batch/<run-id>

.bench-env/venv/bin/python experiments/openevolve_compare/experiment.py prepare-batch \
  --task-set cpu_portable \
  --methods openevolve plain-codex goal-plus-codex goal-plus-pi \
  --run-root runs/openevolve-campaigns/<campaign-id> \
  --wall-time-seconds 300 --concurrency 2 --model gpt-5.6-luna --seed 1
```

`cpu_portable` currently means 12 tasks using only the standard library and locked NumPy/SciPy environment, with no GPU/NPU, downloaded dataset, network service, compiler, or external executable. Batch commands preserve every workspace and record per-cell failures; never delete a partial campaign to retry it.

Standalone benchmarks share one runner while preserving their own task,
artifact, evaluator, raw metric, and metric direction:

```bash
.bench-env/venv/bin/python experiments/benchmark_compare/experiment.py prepare \
  --benchmark autolab-toy-isa --method plain-codex \
  --wall-time-seconds 360 --soft-closeout-seconds 60 --concurrency 2 \
  --model gpt-5.6-sol

.bench-env/venv/bin/python experiments/benchmark_compare/experiment.py prepare \
  --benchmark autolab-toy-isa --method goal-plus-codex \
  --wall-time-seconds 360 --soft-closeout-seconds 60 --concurrency 2 \
  --worker-runtime-seconds 120 --model gpt-5.6-sol
```

Run the printed directory with `experiment.py run --run-dir ... --model ...`.
Supported IDs, task-specific environment requirements, measured verifier time,
and recommended wiring budgets are in
`experiments/benchmark_compare/README.md`. The older
`experiments/heurigym_compare/experiment.py` remains a compatibility entrypoint
to the same implementation.

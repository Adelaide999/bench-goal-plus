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

`bootstrap` creates the disposable `.bench-env/venv`, clones missing pinned OpenEvolve and Goal Plus checkouts as siblings, installs the locked Python environment, and refuses to rewrite an existing checkout at another commit. On another machine, recreate `.bench-env`; do not copy a virtualenv between hosts.

Prepare and verify a model-free Goal Plus task workspace:

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

Prepare `openevolve`, `plain-codex`, `goal-plus-codex`, and `goal-plus-pi` separately. Goal Plus prepare freezes only task plumbing and an empty Search run outside `T`; candidates and workers belong to the timed region. See `docs/reproducible-environment.md` for Mac/Linux details and failure semantics.

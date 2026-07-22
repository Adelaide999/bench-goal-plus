# OpenEvolve task four-path comparison

This harness runs one pinned OpenEvolve example through four independent paths while sharing the seed, official evaluator, model identity, wall-clock budget `T`, and live concurrency `K`:

- `openevolve`: native OpenEvolve population/island search;
- `plain-codex`: `K` independent Codex lanes, followed by controller selection;
- `goal-plus-codex`: Goal Plus fixed parallel lineages hosted by Codex;
- `goal-plus-pi`: the same Goal Plus contract hosted by Pi RPC workers.

Defaults are `T=300s`, `K=2`, model `gpt-5.6-luna`, and reasoning `high`. All four paths require the same explicit OpenAI-compatible `--api-base` and inherit `OPENAI_API_KEY`; the key is never serialized.

For a no-target Goal Plus run, `T` is a cap and `T-closeout` is a minimum exploration duration. The default five-minute protocol therefore requires at least 240 seconds of live orchestration/search and uses 60-second worker dispatches so the same lineage can continue within the remaining budget.

## What is outside and inside T

`prepare` performs task materialization for every method. For Goal Plus it also creates the goal/triage record, freezes the adapter-owned verifier contract, and creates an empty Search run. This mirrors OpenEvolve config preparation and makes the timed region measure search orchestration and workers instead of repeatedly spending most of a five-minute run reconstructing benchmark plumbing.

The prepared Goal Plus state contains no candidates or model output. Inside `T`, the main agent must plan exactly one initial batch, materialize `K` candidates, and launch the fixed lineages. At `T`, the controller stops/drains the host; outside `T` it performs the same kind of deterministic final evaluation/selection already required by the other paths. The manifest reports setup calls separately from timed-plus-closeout calls.

An end-to-end intake-overhead study should be labeled separately and must not be mixed into this search-stage table.

## Prepare

Bootstrap first, then prepare one persistent but Git-ignored directory per method:

```bash
python3 scripts/repro_env.py bootstrap
python3 scripts/repro_env.py doctor

for method in openevolve plain-codex goal-plus-codex goal-plus-pi; do
  .bench-env/venv/bin/python experiments/openevolve_compare/experiment.py prepare \
    --method "$method" \
    --task-id function_minimization \
    --wall-time-seconds 300 \
    --concurrency 2 \
    --model gpt-5.6-luna \
    --seed 1
done
```

Each command prints `runs/openevolve-compare/<run-id>`. Run directories are never automatically deleted. Goal Plus state stays under that run's `workspace/.gp`; evaluator tickets stay in the controller-owned run directory rather than candidate workspaces.

Before spending model budget, the optional seed check is:

```bash
.bench-env/venv/bin/python experiments/openevolve_compare/experiment.py seed-smoke \
  --run-dir runs/openevolve-compare/<run-id>
```

Do not run `seed-smoke` on the same directory intended for a later capped campaign unless that extra evaluator call is explicitly part of the protocol.

## Execute

Set the key only in the shell and run each prepared directory with the same endpoint/model:

```bash
export OPENAI_API_KEY='<secret>'

.bench-env/venv/bin/python experiments/openevolve_compare/experiment.py run \
  --run-dir runs/openevolve-compare/<run-id> \
  --model gpt-5.6-luna \
  --api-base https://api.example.com/v1
```

Codex uses an explicit run-local custom provider over the Responses wire API. Headless Goal Plus MCP tools are registered explicitly with server-level tool approval; no user `config.toml` provider redirect is required. Pi receives a run-local `models.json` whose credential field is only `$OPENAI_API_KEY`.

The outer controller sends `SIGTERM` at `T`, allows a fixed grace period, and marks a hard kill incomplete. A normal deadline signal is accepted only after deterministic closeout succeeds. `experiment.json`, `final-eval.json`, event logs, Goal Plus state, selected artifact, evaluator call counts, and available usage telemetry remain in the ignored run directory.

Goal Plus completion also requires all of the following:

- exactly the prepared Goal Plus ID and linked Search run, with no duplicate Goal;
- exactly `K` candidates and a bound native worker for every candidate;
- zero unbound sessions (controller-created sessions are not proof that workers launched);
- no no-target exit before `T-closeout`;
- successful controller closeout, promotion/report, and common final evaluation.

These gates were exercised by the [strict Codex/Pi rerun](../../evidence/runs/2026-07-22-goal-plus-codex-pi-strict-rerun.md), including diagnostic runs that are intentionally retained as `incomplete`.

If the host process is interrupted after workers finish but before Goal Plus selection/reporting completes, recover the same directory without starting another model run:

```bash
.bench-env/venv/bin/python experiments/openevolve_compare/experiment.py closeout \
  --run-dir runs/openevolve-compare/<run-id>
```

Closeout is idempotent: it reuses an existing promotion, applies its patch to the task source at most once, and completes linked Goal Plus records/reporting.

The first real four-path smoke and its telemetry limitations are recorded in [the sanitized evidence summary](../../evidence/runs/2026-07-22-openevolve-four-path-5m-summary.md).

## Interpretation

This is a wall-time/concurrency comparison, not a token-matched causal ablation. Always report:

- final raw benchmark metric and direction;
- actual wall time and whether the deadline fired;
- candidate/iteration/evaluator-call counts;
- top-level and worker token/cost coverage;
- setup exclusions and controller closeout time;
- any retry, incomplete state, or missing telemetry.

Use evaluator-call matching only in a separately labeled mechanism ablation.

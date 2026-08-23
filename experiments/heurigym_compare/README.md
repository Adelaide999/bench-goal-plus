# HeuriGym Plain Codex / Goal Plus + Codex comparison

This is the first non-OpenEvolve benchmark using the standard experiment
contract. Both paths receive the same task text, official evaluator, model,
wall-clock cap `T`, and concurrency `K`:

- Plain Codex starts `K` isolated Codex lanes and selects the lowest valid
  `total_cost`.
- Goal Plus + Codex starts from the same ordinary Codex task prompt with only
  the `$goal-plus` prefix and aligned Goal Plus configuration appended.

Goal, frozen spec, Search run, candidates, sessions, and `.gp/` state are all
created after the timed invocation starts.

## Bootstrap

All managed repositories live under one ignored directory. A task-specific
bootstrap also installs the always-required OpenEvolve and Goal Plus runtimes:

```bash
python3 scripts/repro_env.py bootstrap --only heurigym
python3 scripts/repro_env.py doctor --only heurigym
```

The resulting checkouts are `third_party/openevolve`,
`third_party/muyuan`, and `third_party/heurigym`; Goal Plus is resolved from
`third_party/muyuan/plugins/goal-plus`. Do not copy `.bench-env`
or `third_party` to another machine; rerun bootstrap there.

## Prepare and run

Prepare a fresh ignored run directory for each method:

```bash
.bench-env/venv/bin/python experiments/heurigym_compare/experiment.py prepare \
  --method plain-codex --wall-time-seconds 300 --concurrency 2 \
  --model gpt-5.6-sol

.bench-env/venv/bin/python experiments/heurigym_compare/experiment.py prepare \
  --method goal-plus-codex --wall-time-seconds 300 --concurrency 2 \
  --worker-runtime-seconds 120 --model gpt-5.6-sol
```

Each command prints its run directory. A no-model seed check is available, but
it consumes an additional public evaluator call and should not be mixed into a
strict campaign ledger:

```bash
.bench-env/venv/bin/python experiments/heurigym_compare/experiment.py seed-smoke \
  --run-dir runs/heurigym-compare/<run-id>
```

Run either prepared directory with native Codex authentication:

```bash
.bench-env/venv/bin/python experiments/heurigym_compare/experiment.py run \
  --run-dir runs/heurigym-compare/<run-id> --model gpt-5.6-sol
```

An explicit OpenAI-compatible provider is optional; when used, keep its key in
the environment and pass `--api-base`. No key is serialized.

At deadline, the controller sends `SIGTERM`, waits a bounded grace period,
performs deterministic Goal Plus closeout, and runs one common final evaluator.
Exactly `K` candidate sessions must be created and bound. At least one worker
must have submitted verifier evidence for a Goal Plus smoke to count as wired;
worker completion count is still reported because a deadline may interrupt a
lineage. A matched campaign should report this utilization difference rather
than silently treating it as `K` completed attempts.

If deterministic closeout or result classification was interrupted, rerun it
without another model call:

```bash
.bench-env/venv/bin/python experiments/heurigym_compare/experiment.py closeout \
  --run-dir runs/heurigym-compare/<run-id>
```

The first real run is summarized in
[`evidence/runs/2026-07-22-heurigym-operator-scheduling-codex-goal-plus.md`](../../evidence/runs/2026-07-22-heurigym-operator-scheduling-codex-goal-plus.md).

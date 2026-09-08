# ZSoft L1 PoC adapter

Wraps the CyberGym ZSoft L1 PoC framework checked out at
`third_party/zsoft-bench/benchmarks/vulnerability/zsoft-l1`
(sparse checkout of `gitcode.com/linmalin/muyuan-sec.git` branch
`linmalin-zsoft-benchmarks-mr`,
framework version 0.1.0).

The adapter:

- calls the benchmark's own `zsoft_poc` CLI via `PYTHONPATH=src` (no `pip
  install`, zero mutation of the benchmark tree);
- materializes one Git workspace per task: the task's exported `public/`
  bundle, a placeholder `poc` artifact, `TASK.md`, `AGENTS.md`, and a
  self-contained `public_check.py`;
- keeps `public_check.py` as a local format gate, then runs `python3 -m
  zsoft_poc evaluate <task-id> <file> --submission-kind final` as the
  controller-owned process verifier for every submitted Goal Plus iteration;
- freezes the selected task's official evaluator timeout plus the existing
  CLI/cleanup margin for its process verifier: the 180-second ASan sample uses
  360 seconds, while a 900-second task uses 1080 seconds;
- records only binary `success` in Search evidence. Once a clean, settled
  iteration records `success=1`, the campaign controller stops exploration,
  selects and promotes that verifier-backed candidate, and runs the final
  judge again. A configured worker minimum runtime remains frozen and audited,
  but its completion requirement is waived only when that controlled stop is
  confirmed by the controller-owned final judge;
- requires Goal Plus Pi workers to use Bubblewrap with only the candidate
  workspace mounted and `public/` read-only; upstream `private/`, judge, and
  reference-PoC files and raw judge output remain host-only. Worker-visible
  verifier and Global Evidence responses contain the binary `success` signal,
  objective Views, and, when enabled, verified shared-tool metadata;
- preserves the full EvaluationResult only under `zsoft_result` in the
  controller-owned final report. Parallel process evaluations use isolated
  staging directories, and a second final claim is rejected before the judge
  is invoked.

Constants:

- `TASK_ID` defaults to `sample-asan-crash`; `configure_task` selects any of
  the 33 task directories (27 formal + 3 samples + kernel tasks).
- the campaign records the managed Muyuan checkout commit, while the pinned
  per-task subject ref is recorded in each workspace as `source_revision`.

Docker is required (`docker compose` must be available). Task preparation must
produce the upstream image references before campaign preparation. Missing
images or Bubblewrap remain environment failures; model-free unit checks do
not prove the protected worker or Docker judge lifecycle.

The reproducible-environment bootstrap owns the default sparse checkout.
`BENCH_GOAL_PLUS_ZSOFT_ROOT` may select another clean checkout for controlled
experiments; the path must remain under this repository.

The official judge remains controller-owned, while its binary result is live
Search feedback. The common runner accepts only `goal-plus-pi` for this adapter,
so every candidate worker uses the protected Bubblewrap execution path.

## Smoke

```sh
python3 -m unittest tests.test_zsoft_l1_adapter -v
```

For model runs use the comparison runner in
[`experiments/benchmark_compare`](../../experiments/benchmark_compare/README.md)
with `--benchmark zsoft-l1`.

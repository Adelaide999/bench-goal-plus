# ZSoft L1 PoC adapter

Wraps the CyberGym ZSoft L1 PoC framework vendored at
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
- exposes only the `format_valid` public gate, which checks that `poc` is a
  bounded, regular, non-symlink UTF-8 file containing parseable Python;
- selects the lowest candidate id with public `process_passed` evidence and
  that candidate's latest compliant iteration, then runs `python3 -m zsoft_poc
  evaluate <task-id> <file> --submission-kind final` exactly once from the
  trusted controller after selection, promotion, and Goal Plus closeout;
- requires Goal Plus Pi workers to use Bubblewrap with only the candidate
  workspace mounted and `public/` read-only; upstream `private/`, judge, and
  reference-PoC files, histories, and verifier results remain host-only;
- reports the official final `success` in {0, 1}, maximize, only after
  closeout. The full EvaluationResult is preserved under `zsoft_result` in the
  controller-owned final report. A second final claim is rejected before the
  Docker judge is invoked.

Constants:

- `TASK_ID` defaults to `sample-asan-crash`; `configure_task` selects any of
  the 33 task directories (27 formal + 3 samples + kernel tasks).
- the campaign records the managed Muyuan checkout commit, while the pinned
  per-task subject ref is recorded in each workspace as `source_revision`.

Docker is required (`docker compose` must be available). On this host the
Docker Hub mirror `docker.m.daocloud.io` is needed for base images such as
`gcc:14-bookworm` — pull and `docker tag` them before the first `prepare`.

The reproducible-environment bootstrap owns the default sparse checkout.
`BENCH_GOAL_PLUS_ZSOFT_ROOT` may select another clean checkout for controlled
experiments; the path must remain under this repository.

Blind Goal Plus runs support only `goal-plus-pi`. `goal-plus-codex` is rejected
before preparation because it lacks the required Bubblewrap worker boundary.

## Smoke

```sh
python3 -m unittest tests.test_zsoft_l1_adapter -v
```

For model runs use the comparison runner in
[`experiments/benchmark_compare`](../../experiments/benchmark_compare/README.md)
with `--benchmark zsoft-l1`.

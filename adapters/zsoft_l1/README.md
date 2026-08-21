# ZSoft L1 PoC adapter

Wraps the CyberGym ZSoft L1 PoC framework vendored at
`third_party/zsoft-bench/benchmarks/vulnerability/zsoft-l1`
(sparse checkout of `gitcode.com/openeuler/muyuan.git` branch `pr-3`,
framework version 0.1.0).

The adapter:

- calls the benchmark's own `zsoft_poc` CLI via `PYTHONPATH=src` (no `pip
  install`, zero mutation of the benchmark tree);
- materializes one Git workspace per task: the task's exported `public/`
  bundle, a placeholder `poc` artifact, `TASK.md`, `AGENTS.md`;
- evaluates by running `python3 -m zsoft_poc evaluate <task-id> <file>
  --submission-kind final`, i.e. the benchmark-owned Docker
  vuln/fix differential judge (no submission server involved);
- reports `success` in {0, 1}, maximize; the full EvaluationResult is
  preserved in the report under `zsoft_result` and in
  `.bench-runtime/history.jsonl`.

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

## Smoke

```sh
python3 -m unittest tests.test_zsoft_l1_adapter -v
```

For model runs use the comparison runner in
[`experiments/benchmark_compare`](../../experiments/benchmark_compare/README.md)
with `--benchmark zsoft-l1`.

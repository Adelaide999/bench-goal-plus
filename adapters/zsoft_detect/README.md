# ZSoft detect adapter

Wraps the cybergym-zsoft-detect static detection benchmark checked out at
`third_party/zsoft-bench/benchmarks/vulnerability/zsoft-detect`
(sparse checkout of `gitcode.com/linmalin/muyuan-sec.git` branch
`linmalin-zsoft-benchmarks-mr`,
framework 1.1.0).

The adapter:

- exports the public bench contract with the benchmark's own
  `scripts/show_bench.py` (project + commit pinned; ground truth and
  matching rules stay hidden);
- materializes an agent workspace with a clean source checkout of the
  exact bench commit (HEAD equality enforced by the runner), the bench
  contract, and `TASK.md`;
- evaluates the candidate's `submission/` directory directly with
  `scripts/score_submission.py --release 0.1.0 --track tp`;
- requires Goal Plus Pi workers to use the adapter-declared Bubblewrap policy:
  only the candidate workspace is mounted, with `source/` read-only, while
  scorer and ground-truth directories remain host-only;
- reports `f1`, maximize; the full score payload (precision/recall/TP/FP/FN)
  is preserved under `zsoft_score` and in `.bench-runtime/history.jsonl`.

Constants:

- default project is `civetweb` @ `d7ba35b…`; `configure_task` accepts any
  of the five project ids (`civetweb`, `jiuwenswarm`, `libxml2`,
  `linux-rxrpc-sample`, `umdk`), optionally suffixed `-detect`.
- the campaign records the managed Muyuan checkout commit, while each
  workspace records the independently pinned audited-source revision as
  `source_revision`.

The benchmark's native runner remains separate from Goal Plus candidate
scoring. Its pinned SWE-agent profile is exposed only through the dedicated
`zsoft-detect-swe-agent` target and `zsoft-swe-agent` method; OpenCode and xiaoO
are not registered methods.

The reproducible-environment bootstrap owns the default sparse checkout.
`BENCH_GOAL_PLUS_ZSOFT_ROOT` may select another clean checkout for controlled
experiments; the path must remain under this repository.
For projects without a public source URL,
`BENCH_GOAL_PLUS_ZSOFT_DETECT_SOURCE_CACHE` may point to an explicitly managed,
clean Git checkout at the pinned project commit. The adapter validates it and
copies its tracked tree into a real workspace `source/` directory without
`.git`; the cache path is not exposed to Pi workers.

## Smoke

```sh
python3 -m unittest tests.test_zsoft_detect_adapter -v
```

# Generic benchmark campaign controller

This controller expands the existing standalone artifact runner into a paired
`benchmark x condition x seed` campaign. It does not own worker scheduling or
replace native evaluators. Every cell still uses
`experiments/benchmark_compare/experiment.py`; the campaign layer owns only the
matrix, durable progress, resume behavior, and derived reports.

## Conditions

| Condition | Existing implementation | Sharing boundary |
|---|---|---|
| B0 | Plain Codex with `K=1` | One isolated long-lived lane |
| B1 | Plain Codex with `K>=2` | Independent lanes, best selected only after the deadline |
| B2 | Not implemented | Runtime cannot expose only final/best while hiding intermediate evidence |
| B3 / way2 | Goal Plus Search Space `observe` | Plans and Evidence are shared; reviewer rejection is recorded but not enforced |
| B4 / way1 | Goal Plus Search Space `enforce` | Plans, Evidence, reject/reserve, verifier linkage, and lineage continuation |

`way0` is also rejected explicitly: Goal Plus does not currently offer the
required combination of hidden plans and disabled Evidence updates with
reject/admission still enabled.

## Lifecycle

Prepare a cheap local matrix without calling a model:

```bash
.bench-env/venv/bin/python experiments/benchmark_campaign/experiment.py prepare \
  --campaign-dir runs/benchmark-campaigns/local-vliw-shakedown \
  --benchmarks local-vliw \
  --conditions B0 B1 B3 B4 \
  --seeds 1 2 \
  --wall-time-seconds 360 --concurrency 2 \
  --worker-runtime-seconds 120 --model gpt-5.6-sol
```

Run prepared cells and inspect progress from another shell:

```bash
.bench-env/venv/bin/python experiments/benchmark_campaign/experiment.py run \
  --campaign runs/benchmark-campaigns/local-vliw-shakedown \
  --model gpt-5.6-sol

.bench-env/venv/bin/python experiments/benchmark_campaign/experiment.py status \
  --campaign runs/benchmark-campaigns/local-vliw-shakedown
```

An interrupted invocation preserves every cell and can be run again. Terminal
cells are skipped. The controller stays in the foreground so the existing
runner retains ownership of Codex deadline handling and process closeout.

`campaign-summary.json` and `campaign-summary.md` preserve native metrics and
add directional gain, evaluator/token totals, best-score trajectory/AUC when
evaluator histories are available, threshold timing when `--threshold
BENCHMARK=VALUE` is supplied, Search Space duplicate/Evidence metrics, and a
paired B1-vs-B4 view. Shared-tool reuse remains explicitly unavailable until
Goal Plus persists attributable tool provenance.

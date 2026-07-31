# Report contract

## Required files

- `report.md`: human-readable campaign summary derived from the native finalizer.
- `<campaign-id>.xlsx`: `Summary` and `Results` sheets, frozen headers, filters, stable field names. It may live in the campaign or a user-selected delivery directory.
- Source evidence remains `comparison.json` for EdgeBench or `campaign-summary.json` for common/OpenEvolve campaigns.

## Required result fields when available

- identity: campaign, benchmark/task, cell, method, model, reasoning, seed;
- budget: `T`, live `K`, cross-task `C`, attempts/trajectories;
- score: raw metric, direction, validity, optional normalized score/directional gain;
- execution: evaluator calls, iterations/rounds, actual runtime;
- usage: input/cached/output tokens and coverage, cost coverage if available;
- protocol: source revision, comparable classification, diff/known issue;
- evidence: run/cell path and error/incomplete reason.

Never replace a missing value with zero. JSON remains the machine source of truth; XLSX is a loss-minimized review view, not a new source of truth.

## EdgeBench filename

The fixed launcher creates ids like:

```text
edgebench-51-codex-gpt-5-6-sol-medium-2h-k1-c2-20260724-1811
```

The default workbook is the same id plus `.xlsx`; `report.md` lives in the campaign directory.

## Delivery path example

Keep `comparison.json` and `report.md` under the campaign, and use `--xlsx-out`
when the user requests a separate delivery location:

```bash
python3 scripts/benchmark_report.py \
  --campaign runs/edgebench/edgebench-51-codex-gpt-5-6-sol-medium-2h-k1-c2-20260724-1811 \
  --xlsx-out "/path/to/output/edgebench-51-codex-gpt-5-6-sol-medium-2h-k1-c2-20260724-1811.xlsx"
```

Treat the absolute path as an example supplied by the user, not a repository
default. Create its parent directory when permissions allow; otherwise keep the
campaign-local workbook and report the delivery failure without changing evidence.

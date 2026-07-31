# Agent lifecycle contract

The repository owns the executable implementation. Skills route user intent into
`scripts/bench.py`; they do not copy benchmark logic.

```text
catalog/check
  -> setup (host gates, bootstrap, doctor, native provision)
  -> launch (prepare, persist agent-run.json, run/detach)
  -> status, recoverable stop, or supported resume
  -> finish (native finalize/summarize, report.md, XLSX)
```

Use `e2e` only when keeping the controller in the foreground is appropriate. For multi-hour native
campaigns, use `launch`, return control to the user, and later continue with `status` and `finish`.
`start` remains only a compatibility spelling of `launch`; do not teach it as a second workflow.

`agent-run.json` only records Agent phase, resolved T/K/C/R, commands, follow-up actions, and a
pointer to native `campaign.json`. It never replaces native state or turns a failed controller into
success.

`benchmarks/runners.json` selects a native, common-matrix, or OpenEvolve batch controller. The
selected benchmark reference defines task isolation, evaluator ownership, model deadlines,
concurrency and durable state. `scripts/benchmark_report.py` remains responsible for
loss-minimized report export.

Docker is part of each target contract: `owner=runner` keeps lifecycle in the native harness;
`owner=adapter` uses adapter hooks or lazy evaluation; `owner=host` means no container for that
exact path. The Agent checks and calls these contracts but does not reimplement benchmark Dockerfiles.

Never write credentials to arguments, plans, manifests, reports, or evidence. Never convert a
missing measurement into zero, and never finalize a non-terminal campaign.

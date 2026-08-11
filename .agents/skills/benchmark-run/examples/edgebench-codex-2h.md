# EdgeBench Codex 2h example

This preset is one concrete campaign, not the scope of `$benchmark-run`.

Inspect the resolved lifecycle without changing the environment:

```bash
python3 scripts/bench.py plan --preset edgebench-codex-2h
```

Launch it with bootstrap, Docker validation, provision, doctor, prepare, and detached run:

```bash
python3 scripts/bench.py start \
  --preset edgebench-codex-2h
```

The preset asserts that `full-codex-2h.json` contains the 50 runnable public Plain Codex tasks;
the official set remains 51, but the known-broken order-addition Judge asset is excluded.
`gpt-5.6-sol/medium`, `T=7200`, `K=1`, `C=2`, and `R=1`. It rejects parameter overrides. To create
a different campaign, use `--benchmark edgebench --profile <profile> --campaign-id <new-id>` so the
campaign ID remains an honest provenance boundary.

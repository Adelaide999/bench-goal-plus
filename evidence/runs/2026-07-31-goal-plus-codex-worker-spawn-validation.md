# Goal Plus Codex worker spawn validation

Date: 2026-07-31

Status: `partial`. The controller now detects a missing Codex worker launch, but the tested
Codex/model stack did not execute `spawn_agent`.

## Environment

- Codex CLI: `0.145.0`
- Goal Plus: `94652c36a381b52b37e7600195b614e932397527`
- Benchmark: `local-vliw`
- Method/model: `goal-plus-codex`, `gpt-5.6-sol`, medium reasoning
- Budget: `T=300`, `K=2`, `C=1`, `R=1`, worker runtime 180 seconds

## Reproduction

```bash
.bench-env/venv/bin/python .agents/skills/benchmark-run/scripts/run_benchmark.py e2e \
  --benchmark local-vliw \
  --campaign-id repair-validation-worker-spawn-contract-20260731 \
  --method goal-plus-codex --seed 1 \
  --model gpt-5.6-sol --reasoning-effort medium \
  --wall-time-seconds 300 --live-search-concurrency 2 \
  --cell-concurrency 1 --worker-runtime-seconds 180 \
  --skip-bootstrap --skip-provision --foreground
```

Credentials and provider URLs were inherited from the host and were not serialized.

## Result

- Campaign state: `partial`
- Successful `spawn_agent` events: `0`, expected at least `2`
- Completed targetless waits: `1`
- Goal Plus candidate/session records: `2` / `2`
- Worker-verified candidates: `0`
- Final controller score: `147734` cycles, unchanged from the seed
- Incomplete reason: `Codex completed 0 spawn_agent calls; expected at least 2 actual workers`

The raw campaign remains under
`runs/benchmark-campaigns/repair-validation-worker-spawn-contract-20260731/`. Its generated outputs
are `report.md` and `repair-validation-worker-spawn-contract-20260731.xlsx`.

Three read-only, one-worker probes reproduced the same behavior with `features.multi_agent=true`,
then with `features.multi_agent_v2=true`, and finally with `agents.enabled=true`. Each probe emitted
a targetless `wait` and a parent-authored answer, but no `spawn_agent` event. This isolates the
remaining failure from Goal Plus intake, Search session creation, and benchmark prompt composition.

## Verified control-plane changes

- Codex uses the documented `agents.max_concurrent_threads_per_session` setting.
- Goal Plus prompts explicitly distinguish session allocation from actual worker spawn.
- Codex JSONL records collaboration tool counts and spawned thread IDs.
- A cell cannot finish when fewer than `K` real spawn events exist.
- Partial Markdown/XLSX reports expose the exact incomplete reason.

Repository validation passed `scripts/status.py --check` and 169 unit tests on the Linux host.

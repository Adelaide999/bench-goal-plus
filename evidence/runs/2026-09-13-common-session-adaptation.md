# Common Adapter Session Verification

## Sources and Scope

- Bench baseline: `f929eba`, plus the accompanying uncommitted adapter changes.
- Goal Plus: `b90fb985a197cbd021f9bf36d7a31d4ab1e3feba`; no core source changes.
- Installed GP build: `4d65afbac03ae57af901cbfebc3fd570a2dae6d15503f5a04a94909963ec42d1`.
- OpenEvolve: `411fb59c886c18704caaffb611e17cf9e7d824d2`.
- Pi: `0.84.2`; model `bench-openai/gpt-5.6-sol`, reasoning `low`.

Common/OpenEvolve and SWE adapters now use public run-local installation,
native session controls and invocation receipts. Retired pool, minimum-lease
and source-root asset assumptions are removed. Optional minimum exploration
and closeout settings are Main planning targets. Protected Pi workers have an
updated MCP proxy; its protocol and mount construction have module coverage.

## Representative Real Run

`session-adaptation-circle-20260913-r2`, task `circle_packing_with_artifacts`,
method `goal-plus-pi`; T=600 seconds, K=1, C=1, R=1 (seed 1).
Runtime provider `direct`, workspace provider `git_worktree`.
Planned closeout reserve=60 seconds; frozen worker maximum=540 seconds.

The public `setup`, `plan`, `launch` and `finish` lifecycle used:

```sh
export BENCH_GOAL_PLUS_SOURCE_DIR=/data/disk/yiyanzhi/muyuan/plugins/goal-plus
export BENCH_GOAL_PLUS_EXPECTED_REF=b90fb985a197cbd021f9bf36d7a31d4ab1e3feba
python3 scripts/bench.py launch --benchmark openevolve-cpu-portable \
  --task-id circle_packing_with_artifacts --method goal-plus-pi \
  --model gpt-5.6-sol --reasoning-effort low --wall-time-seconds 600 \
  --live-search-concurrency 1 --cell-concurrency 1 --seed 1 \
  --pi-provider-id bench-openai --pi-api openai-responses \
  --pi-api-key-env OPENAI_API_KEY --pi-api-base-env OPENAI_BASE_URL \
  --campaign-id session-adaptation-circle-20260913-r2 --skip-bootstrap --skip-provision
```

The installed `/goal-plus` entrypoint created `gp_0001`, linked
`run_20260913_154324_527948c3`, and launched one candidate-bound native session.
One process verifier iteration passed. Seed combined_score was
`0.36423689`; final combined_score was `0.9929830560154846`, validity=1,
sum_radii=`2.6165104`. The exact native interval lasted about 364.46 seconds;
observed peak live workers=1.

Main interrupted and closed the worker at the exploration cutoff and selected
its verified artifact. The outer process reached T and exited after TERM
(return code 143, about 602.87 seconds, no hard kill). Existing controller
closeout took about 39.02 seconds, reused the selection, completed independent
promotion verification and apply, and finished the Goal and both reports.
Cleanup active_count=0. Campaign status is `finished`, without an incomplete
reason. This verifies controller-assisted completion, not autonomous Main
completion within T or a three-round continuation scenario.

[Campaign report](../../runs/openevolve-campaigns/session-adaptation-circle-20260913-r2/report.md)
and its sibling `campaign-summary.json` and XLSX preserve the full local result.

## Preserved Failure and Checks

The first campaign, `session-adaptation-circle-20260913`, remains `partial`.
It recorded score `0.9936128255938685`, then Main started another invocation
without accounting for remaining outer time. Its changed artifact had no new
verifier Evidence at cutoff, so promotion correctly rejected the mismatch.
No historical state was rewritten. The retry prompt exposes the absolute
deadline and requires remaining-time calculations before wake/wait.

Default suite: 527 tests, 2 skipped. Protected Pi suite with the installed MCP
SDK: 22 passed, 8 skipped, 9 subtests passed. The SDK test covers discovery,
successful candidate tool calls and rejection of foreign identity/forbidden tools.
`git diff --check` and affected relative links passed.
Bubblewrap is unavailable here, so real sandbox execution was not verified.
Codex, SWE containers, other benchmark trajectories and GLM were not rerun.
This evidence does not update readiness or claim all benchmark lifecycles pass.

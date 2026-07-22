# Goal Plus + Codex/Pi strict rerun

This rerun uses the current controller code and closes the gap in the first four-path smoke: a result is no longer accepted merely because controller closeout can evaluate and promote seed candidates. Every candidate must have a bound native worker, duplicate/unbound sessions fail, and a no-target search cannot exit before its exploration minimum.

## Protocol

- Task: OpenEvolve `function_minimization`
- Model: `gpt-5.6-luna`, reasoning `high`
- Budget: 300-second cap, 240-second no-target exploration minimum, `K=2`
- Worker dispatch cap: 60 seconds, allowing same-lineage continuation within the outer budget
- Seed label: `4`

## Accepted current-code runs

| Path | Search duration | Bound workers | Search work | Evaluator calls | Final score | Promotion |
|---|---:|---:|---|---:|---:|---|
| Goal Plus + Codex | 290.452s | 2/2; 0 unbound | both workers verified; 3 durable iterations | 11 total; 2 setup | 1.4969813303 | non-empty patch applied |
| Goal Plus + Pi | 250.916s | 2/2; 0 unbound | 10 iterations; 9 terminal pool jobs | 14 total; 2 setup | 1.4274404583 | empty best patch |

Both runs have exactly one Goal Plus record, one linked Search run, two candidates, successful deterministic controller closeout, `promoted` terminal state, persisted report, and a final evaluator score equal to the selected score. Pi no longer creates the duplicate Goal observed in the earlier smoke.

The runs need not hit `SIGTERM`: the five-minute value is an outer cap. With no explicit success target, the controller requires at least 240 seconds of exploration, leaving the configured 60-second closeout reserve. Codex exited at 290 seconds and Pi at 251 seconds, so both pass this rule.

## What the rerun caught

The first fresh Codex retry created four unbound sessions for two candidates and never launched a worker. Deterministic closeout still produced a score, exposing a false-positive acceptance rule. A Pi retry launched workers correctly but stopped after 176.659 seconds despite having no success target. Both raw runs are retained as diagnostics and now become `incomplete` under the controller's strict validation.

The fixes were then rerun, not merely unit-tested: exact intent-only proposal schema, one session/launch per candidate, native binding checks, duplicate-Goal rejection, shorter continuation-friendly dispatches, early-exit rejection, promotion patch application, and common final evaluation all executed in the accepted runs above.

Machine-readable evidence: [2026-07-22-goal-plus-codex-pi-strict-rerun.json](2026-07-22-goal-plus-codex-pi-strict-rerun.json).

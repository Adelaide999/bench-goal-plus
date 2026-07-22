# HeuriGym operator scheduling: Plain Codex and Goal Plus + Codex smoke

This is a wiring result, not a comparative performance conclusion.

## Frozen contract

| Field | Value |
|---|---|
| Task | `operator_scheduling_demo`, five public demo cases |
| HeuriGym fork | `ck0123/heurigym@e394854` |
| Dataset | `heurigen/heurigen-data@c11ab2d` |
| Editable artifact | `solver.py` only |
| Official metric | aggregate `total_cost`, minimize |
| Model | `gpt-5.6-sol`, reasoning `high` |
| Budget | `T=300s`, `K=2` |
| Common prompt SHA-256 | `68601929c8af0ee63a6734ae08e47178aeea9296f1bdb93f88beb66130079fcb` |

The Plain Codex lanes received that common prompt byte-for-byte. Goal Plus +
Codex received the same text with `/goal-plus mode=autonomous` prepended and
the metric, editable surface, verifier, model/host, concurrency, and time
conditions appended. `.gp/` did not exist at prepare time.

## Result

| Method | Seed | Final | Valid | Actual wall time | Search utilization |
|---|---:|---:|---|---:|---|
| Plain Codex | 138 | **62** | yes | 300.20s | 2 lanes; lane 00 selected |
| Goal Plus + Codex | 138 | **95** | yes | 300.07s | 2 candidates and 2 bound Codex sessions; 1 worker verifier submission |

Goal Plus naturally created and completed one Goal record, created two
candidate workspaces and two bound Codex sessions, promoted worker-verified
candidate `c002`, applied its patch, and wrote the report. Candidate `c001` did
not reach a worker verifier call before its 120-second worker deadline; the
controller verified it during closeout. This is preserved as utilization data,
not hidden as a second completed lineage.

The final official per-case costs were:

| Case | Plain Codex | Goal Plus + Codex |
|---|---:|---:|
| demo | 4 | 7 |
| ewf | 21 | 28 |
| hal | 7 | 13 |
| horner | 18 | 18 |
| motion | 12 | 29 |

Plain Codex was better in this one run. Nothing here establishes a method
ranking: there is one seed, no repetition, no native HeuriGym-agent baseline,
and incomplete token telemetry for a deadline-stopped Plain lane and Goal Plus
workers. It does establish that the same benchmark task and evaluator can run
through both standard entries without direct-LLM integration.

Machine-readable evidence is in
[`2026-07-22-heurigym-operator-scheduling-codex-goal-plus.json`](2026-07-22-heurigym-operator-scheduling-codex-goal-plus.json).

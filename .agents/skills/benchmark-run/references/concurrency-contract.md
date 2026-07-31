# Benchmark 并发契约

## Four independent dimensions

| Symbol | Meaning | Manifest field | Comparison rule |
|---|---|---|---|
| `T` | one trajectory/search wall budget | `wall_time_seconds` | fix across compared methods |
| `K` | live within-task search concurrency | `live_search_concurrency` / `concurrency` | fix across compared methods |
| `C` | different cells/tasks run simultaneously | `cell_concurrency` | capacity setting; report explicitly |
| `R` | independent attempts/seeds | attempts/seed matrix | never replace with `C` |

Plain Codex maps `K` to independent isolated trajectories and selects only after the deadline. Goal Plus maps the same `K` to workers sharing one search state. Preserve each native control flow and report evaluator calls, iterations, tokens, cost coverage, and actual wall time after the run.

## Migration standard for a new benchmark

1. Identify the native scheduler and the unit that owns a mutable environment.
2. Ensure every live worker/lane has an isolated resettable workspace unless sharing is the tested mechanism.
3. Put the live `K` bound in the controller/runtime, not only in the prompt.
4. Add `C` only above task cells. Compute host capacity for the worst case and retain native CPU/memory quotas.
5. Use one campaign controller; do not multiply concurrency by launching duplicate controllers.
6. Test `K=1`, then a cheap `K=2` wiring task. Verify peak live processes/containers never exceed the manifest.
7. If these guarantees are unavailable, declare `K=1` support and the missing mechanism as `partial`.

## Example preset

`edgebench-codex-2h` happens to mean `T=7200`, `K=1`, `C=2`, `R=1`. It is an example preset,
not the concurrency default for other benchmarks. The common matrix controller currently declares
`C=1`; do not enable cross-cell concurrency there until isolation and peak resource bounds are tested.

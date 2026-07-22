# OpenEvolve example: four-path 5-minute E2E

This evidence promotes only sanitized facts from ignored raw run directories. No API credential, endpoint, absolute home path, or raw transcript is included.

## Protocol

- Task: OpenEvolve `function_minimization`
- Model: `gpt-5.6-luna`, reasoning `high`
- Budget: `T=300s`, live concurrency `K=2`, seed `1`
- Shared metric: official `combined_score`, maximize
- Seed score: `1.4286455109142118`

## Result

| Path | Final score | Actual T | Search/runtime evidence | Evaluator calls | Result status |
|---|---:|---:|---|---:|---|
| native OpenEvolve | 1.4995399683 | 300.278s | best native iteration 3 | unavailable upstream | finished, graceful deadline |
| plain Codex, 2 lanes | 1.5000000000 | 300.208s | selected lane 1 | 11 total; 2 setup | finished, graceful deadline |
| Goal Plus + Codex | 1.4286455109 | 300.044s | 2 candidates, 2 sessions, 3 iterations, promoted | 7 total; 2 setup | finished, controller closeout passed |
| Goal Plus + Pi | 1.4286455109 | 300.048s | 2 candidates, 2 sessions, 4 iterations, promoted | 8 total; 2 setup | finished after idempotent closeout |

The table proves that all four execution paths reached a durable benchmark result under the requested `T/K/model` contract. It does **not** show a Goal Plus performance win: on this one seed, both canonical Goal Plus runs retained the seed result.

## Important implementation findings

1. A 5-minute unprepared Goal Plus run can spend almost all of `T` on generic goal/spec intake and create zero candidates. The comparable search-stage protocol now prepares the goal, triage, frozen verifier contract, and an empty Search run before `T`; candidate planning, creation, and model work stay inside `T`.
2. Goal Plus promotion returns a patch artifact. The controller must apply it to the task source before the common final evaluator runs. The current closeout does this idempotently. A prior non-empty Codex Search result was repaired and independently re-evaluated at the same `1.4995399972` score.
3. The recorded Pi run hit an old slash-command parsing edge case, creating a second goal linked to the same Search run. Idempotent closeout recovered it. The current runner uses a natural-language prepared-run prompt, and a regression test prevents reintroducing the slash command.
4. Usage coverage is not yet symmetric. Plain Codex emitted terminal usage for one lane; Pi emitted top-level usage; native OpenEvolve did not persist exact calls/tokens; the deadline-stopped Goal Plus Codex parent did not emit terminal usage. These fields must be reported as missing rather than estimated.
5. The raw Goal Plus manifests labeled only the verifier-freeze call as setup. There is also one seed evaluation immediately before `T`, so the promoted table corrects setup from 1 to 2 calls. The current harness snapshots the evaluator ledger at `T0` and reports this split directly.

## Interpretation boundary

This is E2E wiring evidence, not a scientific ranking. It covers one easy task and one seed; evaluator-call and token coverage are not matched. A publishable comparison still needs a frozen task suite, multiple seeds, consistent telemetry, and confidence intervals.

The machine-readable companion is [2026-07-22-openevolve-four-path-5m-summary.json](2026-07-22-openevolve-four-path-5m-summary.json).

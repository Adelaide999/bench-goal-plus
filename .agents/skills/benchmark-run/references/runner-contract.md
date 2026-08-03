# Runner contract

`benchmarks/runners.json` separates reusable lifecycle behavior from benchmark-specific inputs.

## Runner fields

| Field | Meaning |
|---|---|
| `id` / `kind` | Stable runner ID and implementation selected by `runners/factory.py` |
| `controller` | Existing repository controller; the Agent calls it instead of copying it |
| `capabilities` | `provision`, `detach`, `stop`, `resume`, `cell_concurrency`, official evaluator, and exact resume semantics |

Current kinds are `native-profile`, `common-matrix`, and `openevolve-batch`. If a new native
lifecycle cannot implement this interface, add one runner implementation and tests; do not add
target-name branches to the CLI.

## Target fields

| Field | Meaning |
|---|---|
| `id` | CLI benchmark/task-set target |
| `runner` | Reusable runner ID |
| `adapter` | Common artifact adapter, otherwise `null` |
| `bootstrap_targets` | Keys from `environment/upstreams.json` |
| `docker` | Exact execution-path contract described below |

## Docker contract

| Field | Values | Meaning |
|---|---|---|
| `requirement` | `required`, `mixed`, `not_required` | Whether this target path needs Docker |
| `owner` | `runner`, `adapter`, `host` | Which layer owns image/container behavior |
| `provision_mode` | `eager`, `lazy`, `external`, `none` | When provisioning happens |
| `scope` | text | What can and cannot run without Docker |

`runner/eager` means the native controller exposes provision/doctor, as EdgeBench and SWE-EVO do.
For SWE-EVO, SForge owns worker/process-judge images while the vendored SWE-bench harness owns a
second fresh-container final evaluation; the process judge must never be exported as the official
score.
`adapter/eager` requires `provision_environment(upstream_root)` and
`doctor_environment(upstream_root)` hooks. `adapter/lazy` keeps container creation in the existing
evaluator path. `external` means the Agent checks the prerequisite but does not create it.

Presets are frozen examples over targets. They expand model, reasoning, T/K/C/R, methods, and
profile into `agent-run.json`; they are never generic defaults.

## Goal Plus Codex launch evidence

`search_start_agent_session` allocates durable Goal Plus state and returns a launch payload. It
does not itself create a Codex subagent. A completed Goal Plus + Codex cell therefore requires both:

- at least `K` successful `spawn_agent` calls in the top-level Codex JSONL;
- candidate-bound worker verifier evidence in `.gp`.

Treat a session with a bound task name but no matching Codex spawn event as incomplete. This keeps
controller state, actual host execution, and reported concurrency separate.

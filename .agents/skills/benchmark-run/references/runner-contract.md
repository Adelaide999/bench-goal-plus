# Runner contract

`benchmarks/runners.json` separates reusable lifecycle behavior from benchmark-specific inputs.

## Runner fields

| Field | Meaning |
|---|---|
| `id` / `kind` | Stable runner ID and implementation selected by `runners/factory.py` |
| `controller` | Existing repository controller; the Agent calls it instead of copying it |
| `supported_methods` | Canonical methods accepted during plan resolution; unknown methods fail before setup |
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

`runner/eager` means the native controller exposes provision/doctor, as EdgeBench does.
`adapter/eager` requires `provision_environment(upstream_root)` and
`doctor_environment(upstream_root)` hooks. `adapter/lazy` keeps container creation in the existing
evaluator path. `external` means the Agent checks the prerequisite but does not create it.

Presets are frozen examples over targets. They expand model, reasoning, T/K/C/R, methods, and
profile into `agent-run.json`; they are never generic defaults.

## Benchmark-specific completion

This contract does not define one universal completion signal. Read the benchmark reference
selected by [runner-map.md](runner-map.md) for:

- evaluator and native final-artifact ownership;
- required Goal Plus or host-worker evidence;
- detach, stop and resume semantics;
- report source and readiness gates.

Do not promote a benchmark-specific signal such as a SForge Judge trajectory, Codex collaboration
event, or OpenEvolve cell state into the generic runner interface.

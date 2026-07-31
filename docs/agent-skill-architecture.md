# Agent Skill architecture

`bench-goal-plus` is a repository-resident Agent Skill. The Skill understands user intent; the
Python package executes one validated lifecycle.

```text
$bench-goal-plus / specialist Skills
             |
             v
      scripts/bench.py (thin entrypoint)
             |
             v
  bench_goal_plus/application.py
       | catalog + state
       v
 BenchmarkRunner interface
   | native | common | OpenEvolve batch
             |
             v
 existing experiment controller / adapter / official evaluator
             |
             v
 campaign.json + raw evidence -> report.md + XLSX
```

## Why the existing code moved this way

| Before | After | Why |
|---|---|---|
| `scripts/bench.py` contained catalog parsing, setup, dispatch, state, and reporting in one file | It only calls `bench_goal_plus.cli`; application, catalog, state, runtime, and runners are separate modules | Skills and CLI now share one implementation, and lifecycle changes can be tested without importing a monolithic script |
| Every target repeated controller and lifecycle fields | `runners` define reusable behavior once; `targets` bind runner, adapter, upstream, and Docker contract | Adding another common benchmark is data + adapter work, not another launcher branch |
| The dispatcher selected behavior with `if family == ...` throughout the CLI | `BenchmarkRunner` owns prepare/run/status/stop/resume/finalize commands | A benchmark with a new native lifecycle adds one runner implementation without changing every command |
| A generated plan was written as `control-plane.json` | `agent-run.json` records Agent phase, resolved parameters, commands, and the native manifest pointer | The Agent can continue in a later task while the native controller remains the source of truth |
| Docker was only `required/not_required` | Every executable target declares requirement, owner, provision timing, and scope | A future benchmark can retain its own Docker lifecycle or expose adapter hooks without Docker-specific code in Skills |
| EdgeBench, common campaigns, and OpenEvolve batch had separate manual entrypoints | All three expose `plan/start/status/stop-or-resume/finish` where capabilities allow | The user gets one workflow while each method keeps its native execution and evaluator |

## Ownership boundaries

- The Agent owns setup routing, campaign orchestration, normalized status, evidence pointers, and report export.
- Native controllers own scheduling, workspaces, deadlines, container lifecycle, hidden judges, and raw campaign state.
- Common adapters own task materialization and evaluator calls, including lazy Docker evaluation when declared.
- `scripts/benchmark_report.py` reads finalized evidence; it does not alter raw metrics.
- Skills contain instructions and thin wrappers only. They do not copy controller code.

## Durable state

Each newly prepared campaign has two state layers:

- `campaign.json`: runner-owned execution truth.
- `agent-run.json`: Agent-owned phase, resolved `T/K/C/R`, command history, follow-up commands, and report paths.

`status` always reads the runner first and then updates the Agent observation. An old campaign can be
adopted once with `--benchmark`; this adds `agent-run.json` without rewriting native evidence.

## Adding a benchmark with Docker

1. Keep benchmark-specific source and Dockerfiles in its tracked upstream fork.
2. Choose an existing runner or implement the `BenchmarkRunner` interface.
3. Register the target and its upstream checkout.
4. Declare Docker ownership:
   - `runner/eager`: native provision and doctor commands;
   - `adapter/eager`: adapter exposes `provision_environment` and `doctor_environment`;
   - `adapter/lazy`: existing evaluator creates/checks containers at evaluation time;
   - `external`: Agent validates an externally managed dependency;
   - `host/none`: this exact supported path does not use Docker.
5. Test plan output, Docker failure behavior, prepare/state, status, resume/stop capability, native finalization, and report rows.

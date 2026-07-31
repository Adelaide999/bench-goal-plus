# bench-goal-plus contributor rules

This repository is the benchmark operations control plane. It owns benchmark
catalogs, reproducible environments, lifecycle orchestration, method contracts,
evidence normalization, and reports. Goal Plus is one supported method and one
source of observability evidence; it is not the repository architecture.

## Standard Agent workflow

For every benchmark request:

1. Read `python3 scripts/bench.py catalog` and resolve the registered target,
   preset, runner, supported method, Docker contract, and capability flags.
2. Route environment, host, Docker, upstream, and authentication work through
   `benchmark-setup`; run setup/doctor before a real campaign.
3. Route campaign configuration through `benchmark-run`; use `plan` before
   `launch`, record `T/K/C/R`, and return the generated campaign path.
4. For a long run, use `status` and the registered `stop`/`resume` capability.
   Do not replace, delete, or silently restart a partial campaign.
5. After the native campaign reaches a terminal state, route finalization and
   export through `benchmark-report`.
6. Route a new benchmark or task family through `benchmark-adapt`; do not call
   a scaffold or registry entry ready until its acceptance path has evidence.

Before executing a platform- or benchmark-specific command, read the reference
selected by the relevant Skill. Do not infer Linux behavior from macOS,
API-key behavior from OAuth, or one benchmark's lifecycle from another.

## Skill routing

| User intent | Skill | Required reference selection |
| --- | --- | --- |
| End-to-end request or unclear benchmark operation | `bench-goal-plus` | Read its agent contract, then route to one or more Skills below |
| Install, bootstrap, Docker, host compatibility, auth | `benchmark-setup` | Read `host-auth.md` and `benchmark-matrix.md` |
| Plan, launch, monitor, stop, or resume | `benchmark-run` | Read `runner-map.md`, then the selected benchmark/runner reference |
| Finalize, inspect metrics, export Markdown/XLSX | `benchmark-report` | Read `report-contract.md` |
| Add a benchmark or task family | `benchmark-adapt` | Read `adaptation-checklist.md` |

Skills describe operator workflow and route to references. Registries and code
remain executable truth; do not hide host, authentication, or benchmark
differences only inside Python implementation.

## Public contract

- The canonical user entrypoint is `python3 scripts/bench.py`.
- `catalog`, `setup`, `plan`, `launch`, `status`, `stop`, `resume`, `finish`,
  and `check` form the public lifecycle vocabulary. `start` is the compatible
  spelling of `launch`; `e2e` is the foreground convenience path.
- `scaffold` is a contributor tool. Its output is not a readiness claim.
- Skills and benchmark-local scripts may be thin adapters around that
  vocabulary. Do not document a second equivalent public CLI.
- A method must be declared in its runner's `supported_methods` before a plan
  can select it. Reject unsupported methods before setup or preparation.
- A capability shown by `catalog` is a contract. Do not advertise provision,
  detach, stop, resume, cell concurrency, or an official evaluator until tests
  and a reproducible evidence path exist.

## Repository map and ownership

| Path | Owns | Required content | Must not own |
| --- | --- | --- | --- |
| `bench_goal_plus/` | Typed application, catalog, runner, state, event, and reporting contracts | Benchmark-neutral Python modules with fail-closed validation | Benchmark-specific prompts, task IDs, or stopping logic |
| `benchmarks/` | Declarative runner, target, preset, dataset, and evidence registries | Explicit schemas, branch-tracked references, method/capability contracts | Executable orchestration or secrets |
| `environment/` | Reproducible host and upstream definitions | Locked dependencies and one tracking branch per managed checkout | Manual managed-source commit pins or copied virtualenvs |
| `adapters/<benchmark>/` | Common-runner materialization and official evaluation boundary | Task discovery/materialization, evaluator invocation, raw metric and direction | Generic campaign control or vendored upstream source |
| `experiments/<benchmark>/` | Benchmark-owned native lifecycle integration | Profiles, controller, references, and a benchmark-specific README | Cross-benchmark policy or reusable application logic |
| `docker/` | Repository-owned benchmark support images | Minimal Dockerfiles with explicit benchmark purpose and locked inputs | Generic runner policy, credentials, or copied upstream images |
| `local_examples/` | Small repository-owned task fixtures | License/provenance, task README, and deterministic evaluator boundary | Unattributed upstream datasets or claims of full benchmark coverage |
| `evidence/` | Reviewable, committed validation records | Small immutable manifests/summaries with commands, revisions, metrics, and status | Mutable campaign state, credentials, or large raw outputs |
| `legacy/` | Preserved pre-control-plane diagnostics | Clearly labeled compatibility/direct-API tools and migration documentation | New public lifecycle features or readiness claims |
| `scripts/` | Stable entrypoints and small repository maintenance tools | Thin calls into `bench_goal_plus/`; `bench.py` is canonical | Duplicate runner implementations |
| `.agents/skills/` | Operator guidance for the canonical lifecycle | Thin workflow instructions that call `scripts/bench.py` | Broad repository policy or alternative CLIs |
| `docs/` | Explanations, runbooks, protocol rationale, and migration notes | Long-form material linked from code or Skills | Executable truth that is absent from registries/tests |
| `tests/` | Control-plane contracts and regression evidence | Self-contained unit/contract tests runnable in the locked environment | Hidden credentials, network-only assumptions, or disposable run output |
| `.github/workflows/` | Automated repository gates | Locked setup, status validation, and canonical unit suite | Benchmark campaigns or secret-bearing smoke runs |
| `runs/`, `.tmp/`, `.bench-env/`, `.venv/`, `.worktrees/`, `third_party/`, `.codebase-memory/`, `__pycache__/` | Ignored/generated local state | Preserved campaigns, repository-local scratch, recreated environments, managed checkouts, and derived indexes | Hand-authored source intended for this repository |

Every new repository-owned top-level directory needs an ownership row here
before it is used. Nested directories inherit their nearest listed owner's
rules unless their own `AGENTS.md` narrows them.

## Where a change belongs

1. Put reusable lifecycle or evidence behavior in `bench_goal_plus/`.
2. Put declarative identity, support, and capability facts in `benchmarks/`.
3. Put a common-runner benchmark boundary in `adapters/<benchmark>/`.
4. Put an intrinsically benchmark-specific native controller/profile in
   `experiments/<benchmark>/`.
5. Patch a managed upstream only when the behavior belongs to that upstream.
   Keep that change in its `third_party/<checkout>` Git worktree and report the
   root and upstream diffs separately.
6. Put broad policy here. Put operator steps in docs or a Skill.

Never vendor benchmark source or datasets into this repository. Managed source
checkouts track the explicit branches in both `benchmarks/registry.json` and
`environment/upstreams.json`. Preparation records the resolved commit SHA in
the campaign manifest.

## Benchmark integration contract

A benchmark is ready only when all of these exist:

- A target and runner mapping with Docker requirement, owner, provision mode,
  and scope.
- An explicit runner method list and capability declaration.
- A branch-tracked upstream entry or a documented repository-owned fixture.
- A native profile or common adapter that preserves the benchmark's task,
  evaluator, raw metric, and metric direction.
- Contract tests for schema loading, method rejection, plan generation, and
  capability behavior.
- A reproducible `doctor → prepare → run → status → finalize` acceptance path.
- Evidence files that justify every `pass` claim.

Use the benchmark adaptation scaffold documented by the `benchmark-adapt`
Skill for the initial file layout. Generated placeholders are not support:
until the acceptance path is executed, readiness is at most `partial`.

## Evidence and comparison invariants

- Keep official verifier, native baseline, Plain Codex, Goal Plus + Codex,
  Plain Pi, and Goal Plus + Pi readiness claims separate.
- Fix task/evaluator, model, reasoning, wall-clock exploration budget `T`, live
  search concurrency `K`, task-cell concurrency `C`, and repeats `R`. Record
  evaluator calls, tokens/cost coverage, actual wall time, and finalization
  grace rather than silently treating missing values as zero.
- Preserve each method's native control flow and the benchmark's raw metric and
  direction. Put method- or benchmark-specific completion evidence in the
  selected runner reference and enforce it in code/tests.
- Do not pre-create Goal Plus goals, specs, runs, candidates, sessions, or
  `.gp/` before a timed natural invocation. Do not add benchmark-specific
  stopping logic to Goal Plus core.
- Missing required evidence is `partial`, never `pass`.

## Runtime and safety invariants

- Never persist API keys, auth files, cookies, provider headers, or
  secret-bearing command lines.
- Never run Goal Plus from a benchmark source checkout. Materialize a
  disposable Git workspace under ignored `runs/`; keep its `.gp/` there.
- Route `TMPDIR`, `TMP`, and `TEMP` through `bench_runtime_paths.py` to the
  ignored repository-local `.tmp/`. Do not use host-wide `/tmp`,
  `/private/tmp`, or `/var/tmp` for controller state, builds, tests, evaluator
  output, or subprocess scratch.
- Do not delete workspaces, campaigns, or caches automatically. Preserve a
  conflicting path with a `_bak` suffix and report it.
- Before setup, enforce the registry's `docker_requirement` and `docker_scope`.
  If Docker is unavailable, run only `not_required` paths; a `mixed` target may
  use only its named portable task. Never replace a containerized official
  score with a host-only evaluator.
- Preserve raw metrics and their direction. A normalized aggregate is an
  additional field, never a replacement.

## Required verification

Use the locked repository environment for the canonical gate:

```bash
.bench-env/venv/bin/python scripts/status.py --check
.bench-env/venv/bin/python -m unittest discover -s tests -v
```

When changing a managed upstream, also run its focused tests in that checkout.
Before calling a benchmark path ready, exercise its public lifecycle through
`python3 scripts/bench.py` and retain the resulting manifests and evidence.

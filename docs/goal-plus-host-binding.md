# Goal Plus Native Host Contract

Goal Plus derives the Agent family from its authorized Main session. SearchSpec
does not accept `strategy.worker_host`, `worker_launch.agent_profile`,
or `evidence_annotator.host`. Models and reasoning remain
role-specific; this migration does not change their defaults.

Bench selects the native entrypoint through its method (`goal-plus-codex`,
`goal-plus-pi`, or EdgeBench's provider Pi variant). Commands and normalized
evidence use `agent_harness=codex|pi`. Frozen records also require
`runtime_provider=direct` and `spec.workspace.provider=git_worktree|copy`.
The typed command uses `workspace_provider`, and sessions contain a matching
`session_handle` with the native external identity. Missing identity is not
guessed from transport labels, allocated sessions, or old SearchSpec fields.
ThinkThread is outside these Bench execution paths.

EdgeBench, Common/OpenEvolve and SWE-bench adapters install the selected source through `install.sh` and
read its managed runtime receipt. Source assets live under `assets/codex` and
`assets/pi`; old source-root skill trees are not installed. Codex project hooks
come from the generated immutable release and use its isolated launcher.
Pi loads the installer-registered package for both start and resume.
Common/OpenEvolve keep their registration, immutable release and runtime receipt
inside the individual run directory; they do not replace the user's installation.
Host retry admission executes the virtualenv Python path from the installation
receipt directly. It must not use a relocated Python symlink, which can lose
the virtualenv's package search path. The task's default Python is preserved.

Main starts a candidate with `goal_plus_session_run`, observes it with
`goal_plus_session_wait`, and continues the same session with a new call ID when
needed. Main closes the session after delivery. Session allocation alone is not
proof of a model invocation. Archived
`session_handle.metadata.dispatches` provide exact native invocation identities
and execution intervals for concurrency evidence. Missing intervals remain
unknown; process registration/release is not an execution interval. The live
EdgeBench probe no longer checks Goal Plus worker PIDs or retired pool jobs.

At its owned exploration cutoff, EdgeBench records conditional retry admission
through `FileGoalPlusRuntime.stop_for_host_retry` and uses the returned control
version for the same Main session's explicit resume. Goal Plus performs the
state check; the benchmark controller stops its own execution handle. No Goal
Plus process-identity or process-tree helper participates. Finalization grace
does not extend the frozen exploration deadline or permit late process Evidence;
workers must submit that Evidence before the cutoff.

Final completion also requires the archived Goal to be complete, its linked
Search result to be recorded, and both final report files to be present. Missing
or undecodable Goal records fail this gate. Worker success, promotion, and a
valid Judge score remain useful evidence but do not alone complete the Goal.

Bench uses `parallel_loops` with fixed candidates and hard-score selection.
`K` remains `budget.max_parallel`. The retired Scheduler CLI and configuration
are no longer supported. Goal Plus's optional quality scoring and Adaptive
Allocation are not enabled by Bench.

The EdgeBench adapter is owned by the separate checkout at
`third_party/edgebench`, tracking the `mac` branch specified in
`environment/upstreams.json`. Its Pi, provider Pi, Codex, and solo Codex prompts
must be updated together. Updating only this control-plane repository does
not update that fork. Retain and review both diffs before publishing either.

Old Goal Plus frozen records require their original plugin version for runtime
recovery. Current Bench evidence cannot certify their missing execution identity;
original campaign artifacts are preserved. Start a new campaign for the new
contract rather than editing historical `.gp` records.

Common/OpenEvolve development runs may explicitly select a clean external plugin
checkout with `BENCH_GOAL_PLUS_SOURCE_DIR` and `BENCH_GOAL_PLUS_EXPECTED_REF`.
Both are required; HEAD must resolve to the expected ref. Setup verifies this
source without updating it, and plan/cell evidence records its actual branch and
commit. The managed tracking branch is unchanged. Keep the same source selection
through setup, plan, launch, and any resume.

The adapters' optional worker minimum-time, verifier-count, and closeout-reserve
settings are planning targets expressed to Main in the task prompt. They are
not runtime-enforced minimums and are not written into SearchSpec. The current
Goal Plus worker budget only receives the supported maximum runtime and
`on_exceed=interrupt`; its deadline and Evidence gates remain authoritative.
OpenEvolve's default worker maximum is the exploration allocation (`T` minus the
planned closeout reserve); an explicit worker maximum takes precedence. It no
longer imposes the old 30-60 second default. Main explicitly decides whether to
run another turn in a session. Native invocation receipts replace Pi pool jobs
and Codex
minimum-lease files in execution and concurrency evidence.
Before each run or wait, Main receives the absolute deadline and must calculate
the remaining exploration time after its planned closeout reserve. A wait timeout
does not stop a native invocation. Common/OpenEvolve use the same persisted
invocation evidence for Codex and Pi; outer `spawn_agent` events are diagnostic
and are not a prerequisite for workers launched through session tools.

Protected Pi workers load the installed public assets and runtime receipt through
read-only mounts. A benchmark-owned shim at the receipt's Python path routes MCP
through the installed SDK and the existing Unix tool proxy. The host runtime,
store, evaluator files and sibling workspaces remain outside those mounts.
The proxy retains candidate/run identity checks, the tool whitelist, blind
response filtering and one-time host callback capabilities.

Common/OpenEvolve and SWE retain their existing controller closeout paths and
runtime authorization gates. Their timeout policy is distinct from EdgeBench's
same-Main retry: this update does not add automatic Main resume to other runners.

Controller closeout for `promotion_mode=apply` calls `search_apply_promotion`
before recording the Search result. Applying a Git patch alone does not settle
Goal Plus publication state. An unresolved publication keeps closeout incomplete.
If Main already completed publication, closeout reuses its persisted `applied`
state without requesting another mutation on the completed Goal.

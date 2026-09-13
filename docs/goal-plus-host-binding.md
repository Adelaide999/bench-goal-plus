# Goal Plus Native Host Contract

Goal Plus derives the Agent family from its authorized Main session. SearchSpec
does not accept `strategy.worker_host`, `worker_launch.agent_profile`,
`evidence_annotator.host`, or `search_scheduler.host`. Models and reasoning remain
role-specific; this migration does not change their defaults.

Bench selects the native entrypoint through its method (`goal-plus-codex`,
`goal-plus-pi`, or EdgeBench's provider Pi variant). Commands and normalized
evidence use `agent_harness=codex|pi`. Frozen records also require
`runtime_provider=direct` and `spec.workspace.provider=git_worktree|copy`.
The typed command uses `workspace_provider`, and sessions contain a matching
`session_handle` with the native external identity. Missing identity is not
guessed from transport labels, allocated sessions, or old SearchSpec fields.
ThinkThread is outside these Bench execution paths.

Both EdgeBench adapters install the selected source through `install.sh` and
read its managed runtime receipt. Source assets live under `assets/codex` and
`assets/pi`; old source-root skill trees are not installed. Codex project hooks
come from the generated immutable release and use its isolated launcher.
Pi loads the installer-registered package for both start and resume.
Host retry admission executes the virtualenv Python path from the installation
receipt directly. It must not use a relocated Python symlink, which can lose
the virtualenv's package search path. The task's default Python is preserved.

Main prepares a candidate, calls `goal_plus_session_open`, then explicitly uses
`goal_plus_session_wake/wait` for each invocation and closes the session after
delivery. Opening alone is not proof of a model invocation. Archived
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

Scheduler CLI configuration now consists of `--search-scheduler-model`,
`--search-scheduler-reasoning-effort`, `--search-scheduler-timeout-seconds`,
`--search-scheduler-reward`, and `--search-scheduler-allocation`.
Remove `--search-scheduler-host` and the nested `host` key from existing scheduler
configuration files. A nested `host` is rejected instead of silently ignored.
`K` remains `budget.max_parallel`; `max_candidates` is an independent cumulative
limit for Adaptive Search. Without a Scheduler, prompts use `parallel_loops`.

The EdgeBench adapter is owned by the separate checkout at
`third_party/edgebench`, tracking the `mac` branch specified in
`environment/upstreams.json`. Its Pi, provider Pi, Codex, and solo Codex prompts
must be updated together. Codex and Pi consume the controller's encoded Scheduler
instructions when configured. Updating only this control-plane repository does
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

EdgeBench's optional worker minimum-time, verifier-count, and closeout-reserve
settings are planning targets expressed to Main in the task prompt. They are
not runtime-enforced minimums and are not written into SearchSpec. The current
Goal Plus worker budget only receives the supported maximum runtime and
`on_exceed=interrupt`; its deadline and Evidence gates remain authoritative.

Controller closeout for `promotion_mode=apply` calls `search_apply_promotion`
before recording the Search result. Applying a Git patch alone does not settle
Goal Plus publication state. An unresolved publication keeps closeout incomplete.
If Main already completed publication, closeout reuses its persisted `applied`
state without requesting another mutation on the completed Goal.

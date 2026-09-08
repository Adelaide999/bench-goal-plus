# Goal Plus Native Host Contract

Goal Plus derives the Agent family from its authorized Main session. SearchSpec
does not accept `strategy.worker_host`, `worker_launch.agent_profile`,
`evidence_annotator.host`, or `search_scheduler.host`. Models and reasoning remain
role-specific; this migration does not change their defaults.

Bench selects the native entrypoint through its method (`goal-plus-codex`,
`goal-plus-pi`, or EdgeBench's provider Pi variant). The runner-local
`worker_host` identifier is still used for commands and normalized evidence; it
is not emitted into SearchSpec. Current frozen records contain
`native_host=codex|pi`, and local Git/Copy evidence maps these to the Codex or
Pi RPC driver. Missing identity is not guessed from allocated sessions or old
SearchSpec fields. ThinkThread is outside this Bench migration.

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
recovery. Current Bench evidence cannot certify their missing native identity;
original campaign artifacts are preserved. Start a new campaign for the new
contract rather than editing historical `.gp` records.

Common/OpenEvolve development runs may explicitly select a clean external plugin
checkout with `BENCH_GOAL_PLUS_SOURCE_DIR` and `BENCH_GOAL_PLUS_EXPECTED_REF`.
Both are required; HEAD must resolve to the expected ref. Setup verifies this
source without updating it, and plan/cell evidence records its actual branch and
commit. The managed tracking branch is unchanged. Keep the same source selection
through setup, plan, launch, and any resume.

Search prompts use `strategy.config.reserve_closeout_seconds` so candidate
continuation and verifier admission reserve the same finalization window.

Controller closeout for `promotion_mode=apply` calls `search_apply_promotion`
before recording the Search result. Applying a Git patch alone does not settle
Goal Plus publication state. An unresolved publication keeps closeout incomplete.
If Main already completed publication, closeout reuses its persisted `applied`
state without requesting another mutation on the completed Goal.

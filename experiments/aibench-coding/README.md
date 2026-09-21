# aibench coding native integration

This target adapts the `benchmarks/coding` source from the managed aibench fork.
It preserves upstream case materialization and `grade_case` as the official
hidden evaluator while reusing bench-goal-plus orchestration for four methods:
Plain Codex, Plain Pi, Goal Plus + Codex, and Goal Plus + Pi.

## Boundary

- The Agent sees only the materialized `submission/`, the task prompt, and the
  visible tests. A Linux Bubblewrap boundary masks the whole managed aibench
  checkout, including hidden tests and gold files, from the outer Agent and all
  descendants.
- Selection uses visible-test evidence. Goal Plus can finish its public Search
  lifecycle normally; the controller calls the hidden upstream grader once on
  the selected result. Hidden score never participates in selection.
- `task_success` is the raw boolean metric; `task_success_rate` is the
  maximize-direction aggregate. Upstream `max_attempts` and `case_workers` are
  not mapped to benchmark `K` or `C`.

## T/K/C/R

- `T`: one Plain trajectory or one Goal Plus search wall-clock budget.
- `K`: Plain requires K=1; Goal Plus starts one main
  session with K internal subagents sharing one Search state.
- `C`: concurrent task cells in this native campaign controller.
- `R`: independent seeds.

The final report records observed outer trajectories, observed Goal Plus
subagents, evaluator calls, usage coverage, the upstream revision, and whether
each cell is eligible for matched comparison. A K mismatch or missing isolation
evidence makes the cell and campaign `partial` without discarding its score.

## Lifecycle

Use only the unified entrypoint:

```bash
python3 scripts/bench.py catalog
python3 scripts/bench.py plan --benchmark aibench-coding --profile smoke \
  --method plain-codex --model bench-openai/gpt-5.6-sol \
  --wall-time-seconds 300 --live-search-concurrency 1 \
  --cell-concurrency 1 --seed 1
```

`setup`/`doctor` requires Linux, Bubblewrap, the exact managed source branch,
the locked aibench grading runtime, selected Agent binaries, and inherited
OpenAI-compatible provider variables. Runs are foreground-only and
non-resumable. `finish` consumes terminal evidence without re-running the
official grader.

The `goal-plus-pi-glm53flash-smoke` profile uses `zai/glm-5.3-flash`, low,
Completions, T=900, K=1, C=1, R=1, and inherited `ZAI_BASE_URL`/`ZAI_API_KEY`.
Pi retains public `visible_test_score` feedback; hidden `task_success` is
controller-only and does not enter Search. Codex profiles require Responses.
The exact Pi model metadata is projected from the host catalog into the isolated
runtime. An external Goal Plus checkout can be selected with
`BENCH_GOAL_PLUS_SOURCE_DIR` and `BENCH_GOAL_PLUS_EXPECTED_REF`; setup validates
its clean revision and prepare records that identity for execution checks.
Each Pi cell receives a private writable socket directory under `.tmp/`.
Isolated candidates use `goal_plus_search_run_verifier` to execute public tests in the
host grading environment; `python3 evaluate.py` is the Main/Plain entrypoint.

The initial integration remains `partial` until a real Linux+bwrap campaign is
archived for each method. For `K>1`, the report exposes selected-result success
but deliberately leaves pass@K/pass^K unset because unselected trajectories are
not sent to the hidden grader.

## Optional final candidate judge

Goal Plus can use a controller-only tie-breaker after the hard/process gate:

```bash
export GOAL_PLUS_JUDGE=off                 # default
# or: jev / llm-as-a-verifier
```

The switch is accepted only by `goal-plus-codex` and `goal-plus-pi`; plain
methods fail before launch when it is enabled.

`jev` uses `OPENROUTER_API_KEY` (optionally `GOAL_PLUS_JEV_ENDPOINT` and
`GOAL_PLUS_JEV_MODEL`); `GOAL_PLUS_JUDGE_TIMEOUT_SECONDS` bounds the request.
`llm-as-a-verifier` loads the optional `llm_verifier` package and uses its
dedicated `GOAL_PLUS_LLM_VERIFIER_*` settings (a dedicated key must be paired
with `GOAL_PLUS_LLM_VERIFIER_BASE_URL`), or an OpenAI-compatible/native backend
key already present in the controller. Use a separate judge key when strict
controller/worker credential separation is required. The
controller runtime must provide the optional `llm_verifier` package; otherwise
the enabled run is recorded as incomplete rather than silently falling back.
The judge runs once on candidates tied for the best hard/process score, records a bounded selection
receipt, and cannot send feedback to workers or request another search round.
Native Goal Plus Evidence Annotation is disabled while either judge mode is on;
the judge is the only optional quality selector in that run.
`off` performs no network call. Judge-specific credentials are never written to
the manifest and are removed before worker launch; the Agent's own provider
credential remains available to that Agent. The receipt's `calls` field counts the
single controller invocation; the verifier's internal pairwise requests are
reported separately as `comparisons` when available.

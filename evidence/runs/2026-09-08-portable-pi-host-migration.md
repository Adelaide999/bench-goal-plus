# Portable Pi host migration checks

Scope: one OpenEvolve CPU task and the common runner with Pi. These are wiring
checks, not a benchmark comparison or a readiness upgrade for every adapter.

## Environment and command

- Bench base: `6526608`, with the accompanying uncommitted migration changes.
- Goal Plus: `432d1fbcc8d3f7fc0725dcc8292af65ab8cf1eaf`, clean external checkout,
  branch `refactor/goal-plus-consolidated`.
- Pi: `0.84.2`; provider/model `zai/glm-5.3-flash`; reasoning `low`.
- OpenEvolve: `411fb59c886c18704caaffb611e17cf9e7d824d2`.
- AutoLab: `7aff5fe71dfbe152fb0b8e8ac8087210b4bc27d5`.
- Each campaign: T=600 seconds, K=2, C=1, R=1; Git worktree,
  `parallel_loops`, no shared directory and no Adaptive Scheduler.
- Authentication remains inherited through `ZAI_API_KEY`. The isolated Pi model
  config projects exact model metadata from the host catalog, excluding auth.

Use the same selection for `plan` and `launch`, after `setup` succeeds:

```bash
export BENCH_GOAL_PLUS_SOURCE_DIR=/data/disk/yiyanzhi/muyuan/plugins/goal-plus
export BENCH_GOAL_PLUS_EXPECTED_REF=refactor/goal-plus-consolidated
export ZAI_BASE_URL=https://api.z.ai/api/coding/paas/v4
python3 scripts/bench.py launch \
  --benchmark openevolve-cpu-portable --task-id function_minimization \
  --method goal-plus-pi --model glm-5.3-flash --reasoning-effort low \
  --pi-provider-id zai --pi-api openai-completions \
  --pi-api-key-env ZAI_API_KEY --pi-api-base-env ZAI_BASE_URL \
  --wall-time-seconds 600 --worker-runtime-seconds 60 \
  --live-search-concurrency 2 --cell-concurrency 1 \
  --campaign-id <new-id> --skip-bootstrap --skip-provision --foreground
python3 scripts/bench.py status --campaign <campaign-path>
python3 scripts/bench.py finish --campaign <campaign-path>
```

For common-runner checks, replace benchmark/task selection with
`--benchmark autolab-toy-isa` (no task-id). The diagnostic VLIW attempt used
`--benchmark local-vliw` and a 180-second worker lease.

## OpenEvolve result

Campaign: `runs/openevolve-campaigns/oe-pi-glm53flash-k2-r2-20260908`.

- Independent final evaluator: valid, `combined_score` increased from
  `1.4286455109142118` to `1.4995399694450207` (maximize).
- Goal `complete`; Search `run_20260908_031816_72a4bd22` promoted and applied.
- Two bound worker sessions and two worker-verified candidates; four candidate
  iterations; observed peak concurrency 2. Fifteen evaluator calls total.
- Controller exited successfully and reused Main's promotion. Main itself hit
  the time cap: 601.06 seconds, SIGTERM/143, no SIGKILL. Pool cleanup recorded
  closed pools, zero active jobs, and no close timeout.
- The earlier campaign `oe-pi-glm53flash-k2-20260908` resolved the model to
  `glm-5.3` and was stopped. It is retained as an invalid configuration attempt.
- The successful run preceded the final candidate-ID pool prompt wording; the
  Main recovered from an empty pool. It does not prove error-free startup.

## Common runner diagnostic

Campaign: `runs/benchmark-campaigns/generic-vliw-pi-glm53flash-k2-20260908`.

- Two real Flash workers started. Their first leases made no delivered edits;
  automatic final verification correctly skipped unchanged workspaces.
- A later verifier request was refused because remaining time could not cover
  its frozen 61-second suite bound plus the 60-second closeout reserve.
- Controller closeout exposed an adapter defect: direct Git patch application
  did not settle Goal Plus publication. Result recording was correctly refused
  with `Call search_apply_promotion before recording a Search result`.
- Campaign remains `partial`/cell `incomplete`; independent final evaluation was
  withheld. The subsequent fix calls the public publication API and refuses
  unresolved application before recording the result. Regression tests cover it.
- This is a repository-owned VLIW replica, not official EdgeBench evaluation.

## Coverage and limits

### Common runner final check

Campaign: `runs/benchmark-campaigns/generic-autolab-pi-glm53flash-k2-20260908`.

- Independent final evaluator: valid; cycles decreased from `9220` to `1898`.
- Goal `complete`; Search `run_20260908_034254_eda2405a` promoted and applied.
- Two bound worker sessions, two worker-verified candidates, four attempts, peak
  concurrency 2. Seven evaluator commands/calls in the recorded coverage.
- Main exited normally, return code 0 after 583.20 seconds, before T. Pool
  cleanup recorded closed, zero active jobs, and no close timeout.
- Initial controller closeout unnecessarily called apply again after Main had
  completed the Goal. The trusted authorization gate refused this mutation.
  The fix reuses persisted `publication.state=applied` without mutating the
  completed Goal. Regression coverage checks both unresolved application and
  replay after completion.
- Existing deterministic `experiments/benchmark_compare/experiment.py closeout
  --run-dir <cell>` successfully repaired closeout and performed the independent
  final evaluation without new model calls. `scripts/bench.py finish` exported
  the updated result. Cell state is `finished`; the campaign's cached controller
  state remains `partial` from the initial exit. This is a repaired lifecycle
  result, not an uninterrupted green launch. The initial error remains in the
  execution record beside `goal_plus_controller_closeout_repair`.

### Verification limits

- Focused tests: 96 passed, one known blind-prompt assertion deselected.
- Default suite: 494 tests, 5 failures and 19 errors. The failure set matches the
  earlier run: missing Frontier/ZSoft/SWE assets, outdated controller fixtures,
  ambient-auth fixture behavior, blind-prompt and runtime-path assertions.
- `scripts/status.py --check` and `git diff --check` passed.
- SWE-bench local inventory lacks
  `swebench/sweb.eval.x86_64.sympy_1776_sympy-16886:latest`; no SWE E2E claimed.
- Optional B3/B4 Search Space and protected blind workflows are not validated by
  this check. Main still spends time correcting generated SearchSpec fields.
- No push performed. Raw campaigns and their Markdown/XLSX reports are retained
  locally; this record contains no credentials or raw transcripts.

## SWE single-image follow-up

The user subsequently authorized pulling one official task image and attempting
the single-case workflow. The exact SymPy smoke image was downloaded:

- Image: `swebench/sweb.eval.x86_64.sympy_1776_sympy-16886:latest`.
- Registry digest: `sha256:8e68941a90d2b34aaedf409876a2353e3ffc7cb8b70c90bb543bea626c5da085`.
- Local image ID: `sha256:ef6962cc38502486b14a8673524bd43e6a6a6547d02c4b7b1715e74458362366`.
- Architecture: `amd64`; image size: 2,759,521,824 bytes.
- The profiled local-asset check now passes. The earlier missing-image finding
  above records the pre-download state.
- Host/Docker architecture is `aarch64`; no x86 QEMU/binfmt handler or alternate
  Docker context is configured. An isolated `--network none --pull never`
  container executing only `/bin/true` failed with `exec format error`.
- The probe container was automatically removed. No model or official evaluator
  ran. The current SWE runner also requires an x86_64 Docker daemon; this is an
  execution-platform blocker, not a benchmark score or a model failure.

Logs remain in `.tmp/swe-single-image-pull-20260908.log`,
`.tmp/swe-single-inventory-after-20260908.json`, and
`.tmp/swe-single-image-exec-20260908.log`.

An official ARM image for the same case was subsequently found and pulled;
the x86 execution-platform blocker above is not a lack of ARM task availability.
See [the ARM follow-up](2026-09-08-swe-arm-pi-glm53flash.md) for exact image
identity, runner adaptations, and separate campaign evidence.

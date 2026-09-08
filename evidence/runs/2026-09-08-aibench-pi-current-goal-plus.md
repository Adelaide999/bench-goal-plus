# AIBench Pi with current Goal Plus

## Configuration

- Host: Linux aarch64, Pi 0.84.2, Bubblewrap 0.8.0; no Docker.
- Goal Plus: clean external checkout, expected ref
  `refactor/goal-plus-consolidated`, commit
  `432d1fbcc8d3f7fc0725dcc8292af65ab8cf1eaf`.
- AIBench: managed `coding-benchmark`, commit
  `3a6885b5be902fd6bf108c9baa65a89b790b1cfe`.
- Case: `rev-09f7740f614d3ea9`, `_clean2026` set fingerprint
  `9149d02169845dc5`, valid-only selection.
- Profile: `goal-plus-pi-glm53flash-smoke`; exact `zai/glm-5.3-flash`, low,
  Completions. T=900 seconds, K=1 internal worker, C=1 task cell, R=1 seed;
  worker limit 120 seconds, closeout reserve 120 seconds, no shared-dir.
- `BENCH_GOAL_PLUS_SOURCE_DIR` and `BENCH_GOAL_PLUS_EXPECTED_REF` selected
  the current source. `ZAI_BASE_URL` and `ZAI_API_KEY` were inherited;
  no credential value is included in this record.

The public lifecycle was `catalog`, inventory `check`, `setup`, `plan`,
`launch`, `status`, and `finish`. Final plan/launch flags were:

```text
--benchmark aibench-coding --profile goal-plus-pi-glm53flash-smoke
--method goal-plus-pi --model zai/glm-5.3-flash --reasoning-effort low
--wall-time-seconds 900 --live-search-concurrency 1 --cell-concurrency 1
--seed 1 --campaign-id aibench-pi-glm53flash-r6-20260908
--foreground --skip-bootstrap --skip-provision
```

## Acceptance

Campaign `runs/aibench-coding/aibench-pi-glm53flash-r6-20260908` completed
without repair. `finish` archived the summary, Markdown report and XLSX.

- Main exited 0 after 322.346 seconds, without deadline expiration or hard kill.
- Search `run_20260908_080247_1a4325ed` froze native host Pi,
  `git_worktree`, `parallel_loops`, and `autoresearch`.
- One outer Main, one bound Pi worker session, one candidate, and one clean
  kept worker iteration; topology matches K=1. Worker execution took 52.348
  seconds and submitted its own verifier result.
- Public `visible_test_score` improved from 0 to 1. Main selected, promoted,
  applied the publication, completed Goal audit and generated the report.
- Hidden official final `task_success=true`, valid=true, with six tests
  passing. Hidden grading ran once, after Search, and did not affect selection.
- Four recorded evaluations: setup seed, worker process, promotion, final.
- Controller reused the already-applied publication. Pool closed with
  active_count=0 and close_timed_out=false; there was no session recovery.
- Outer sandbox masked the hidden checkout and peer cells. Worker sandbox
  exposed its submission and public feedback, with private host callback
  scratch and a read-only generation projection.

This is one workflow acceptance case, not a matched method comparison or
coverage of all AIBench tasks. The earlier Codex evidence uses a different
model/revision and is not pooled with this result.

## Preserved Attempts and Fixes

All attempts are retained under `runs/aibench-coding/` with their logs.

| Campaign suffix | Outcome and correction |
| --- | --- |
| `aibench-pi-glm53flash-20260908` | Preparation rejected visible public feedback combined with controller-only hidden grading. Decouple feedback visibility from final evaluator ownership in adapter validation, prompt and closeout. |
| `r2-20260908` | Outer sandbox left the worker Unix-socket directory read-only. Allocate and mount a private, short repository-local directory per cell. No worker model session started. |
| `r3-20260908` | Context succeeded but current Pi's generation guard could not read its private runtime projection. Add only the bound generation, read-only; preserve real host session gates. |
| `r4-20260908` | Worker modified and verified successfully, but a blind-only closeout restriction blocked Main's public Search completion. Apply that restriction only to blind feedback. The Goal became blocked; the campaign remains partial. |
| `r5-20260908` | Pi model preflight returned aborted before creating any Goal. Preserve the failed preflight; retry the same exact model. |
| `r6-20260908` | Completed with official task_success=true and all required evidence. |

The adapter also forwards the configured Pi API, preserves exact model catalog
metadata, validates the external Goal Plus source identity, and distinguishes
Main/Plain script execution from isolated candidates' host verifier tool.
The shared protected-worker callback fixes are described in the
[ZSoft record](2026-09-08-zsoft-pi-current-goal-plus.md).

## Final Checks

- `.bench-env/venv/bin/python -m pytest -q --tb=short tests`: 544 passed,
  502 subtests passed, with Bubblewrap available and a private XDG runtime.
- `.bench-env/venv/bin/python -m unittest discover -s tests -v`: 523 passed.
- Registry validation: 16 items and 8 datasets passed; `git diff --check` passed.
- Goal Plus and ZSoft upstream worktrees remained clean. No push was performed.

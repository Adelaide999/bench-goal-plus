# Frontier and ZSoft adaptation to current Goal Plus

## Sources

- Host: Linux aarch64; Frontier CPU path uses no Docker.
- Bench worktree base: `6526608`, with the uncommitted adapter changes in this
  change set. Nothing was pushed.
- Goal Plus: external clean source, expected ref
  `refactor/goal-plus-consolidated`, commit
  `432d1fbcc8d3f7fc0725dcc8292af65ab8cf1eaf`.
- Frontier: managed `main`, commit
  `e3fa29c193356af2ce1ec8b3d23ab1a2e2410071`.
- ZSoft: managed `linmalin-zsoft-benchmarks-mr`, commit
  `7967e9e7c95d30decb19b525c9cad6533e83ff59`.

## Failure attribution and fixes

The earlier failures were not all missing assets. Comparisons with committed
history and current public Goal Plus return models established these causes:

| Area | Cause and correction |
| --- | --- |
| ZSoft protected Pi worker | Old candidate context, iteration and verifier response whitelists rejected current public results; list-iterations still required obsolete run/candidate arguments. Update the projection and session-only API while keeping private artifact handles out of worker feedback. |
| ZSoft worker identity | Bind the proxy and sandbox role/session from trusted LaunchContext, not inherited environment values. |
| ZSoft L1 | A live judge still received the old 120-second process verifier timeout. Use its actual 1080-second evaluator contract. |
| ZSoft batch setup | Forward the same explicit DeepSeek provider and completion API settings already used by launch. |
| ZSoft posthoc | Eligible, clean `discard` iterations were excluded despite representing valid submissions. Include them and use current `artifact_clean` evidence. Preserve public validity, edit-surface and immutable Git checks. |
| Frontier Pi | Carry profile provider/API/environment names through doctor, preparation, Main and worker. Preserve exact host catalog metadata for Z.AI Flash. |
| Frontier source | Doctor wrongly compared an explicitly authorized external Goal Plus ref with the managed branch. Reuse external source identity validation and expose it in native plan metadata. |
| Frontier evaluator shell | Upstream `bash -lc` loaded a host profile that changed cwd. Configure a shell with login profiles disabled; include the shell in the frozen evaluator hash. |
| Frontier deadline admission | The blanket 300-second verifier reservation prevented this subsecond task from verifying during a 600-second Search. Set EnergyStorage's recorded timeout to 30 seconds across doctor/process/promotion/final evaluation. |
| Common campaign | Commit `f812457` introduced subprocess cells but lost Codex API-base forwarding. Restore it and exercise the subprocess boundary in the resume test. |
| Stale tests | Correct old blind-sharing assertions from before `1cfe4cfe`, OAuth tests inheriting live API credentials, incomplete portable manifests/seed results, and a tempfile check that rejected explicit run-owned directories. |

Frontier's unit protocol fixtures no longer require the upstream checkout.
Its actual doctor still requires and verifies upstream task/evaluator assets.

## Frontier real acceptance

Profile: `energy-storage-goal-plus-pi-glm53flash-smoke`.
Model: `zai/glm-5.3-flash`; Main and worker launch use low reasoning.
T=600 seconds per Search; K=1 internal worker; C=1 task at a time; R=1 seed.
Shared-dir is disabled. Runtime installation uses the common source installer
and the public Goal Plus lifecycle.

The public lifecycle was executed with these inherited settings:

```bash
export BENCH_GOAL_PLUS_SOURCE_DIR=/data/disk/yiyanzhi/muyuan/plugins/goal-plus
export BENCH_GOAL_PLUS_EXPECTED_REF=refactor/goal-plus-consolidated
export ZAI_BASE_URL=https://api.z.ai/api/coding/paas/v4
# ZAI_API_KEY is inherited; its value is not recorded.
```

After catalog/inventory and managed setup/provision, the repeat used
`scripts/bench.py setup --benchmark frontier-engineering
--profile energy-storage-goal-plus-pi-glm53flash-smoke --skip-bootstrap
--skip-provision`, followed by `plan` and `launch` with the same target/profile,
`--campaign-id frontier-flash-current-r2-20260908 --method goal-plus-pi
--model glm-5.3-flash --reasoning-effort low --wall-time-seconds 600
--live-search-concurrency 1 --cell-concurrency 1 --skip-bootstrap
--skip-provision`. Both attempts were observed through `status` and archived
through `finish`.

- First attempt: `runs/frontier-engineering/frontier-flash-current-20260908`.
  Preserved as interrupted, with no final score. Worker verification was
  refused because its frozen 300-second suite plus closeout reserve exceeded
  remaining time. Stop was requested, but this native controller finished the
  current cell at its time boundary before returning interrupted.
- Second attempt:
  `runs/frontier-engineering/frontier-flash-current-r2-20260908`.
  Campaign completed, Goal complete, Search promoted and public apply recorded.
  Controller reused the already-applied publication and ran official final
  evaluation. It did not modify Goal Plus state to bypass a gate.
- Seed and final `combined_score`: **66.16356426696784**, maximize;
  final valid=true, no improvement. This is workflow acceptance, not evidence
  of optimization quality.
- One bound worker session and one verified candidate; observed peak worker
  concurrency=1. One process verifier, one promotion verifier and one
  controller final evaluation, plus one setup seed evaluation: four total.
- One Annotation task completed. Worker launch records confirm low reasoning.
- Main reached its 600-second cap, exited on SIGTERM (143), with no hard kill.
  Controlled wall time was 601.065 seconds; required closeout evidence passed.
- A late continuation could not fit 31 seconds of verification plus the
  60-second closeout reserve in 68.4 remaining seconds. Its job retained the
  deadline error; already-settled Evidence remained usable and was promoted.
- The second run froze `inner_agent=common`, a supported Pi driver. After both
  runs showed the model confusing strategy name with inner-agent identity,
  the shared prompt was clarified to request `autoresearch` explicitly.
  That final wording passed focused regression; this Frontier run is not
  claimed as real-host evidence for the subsequent wording change.
- No full-cost claim: existing usage coverage combines Main and Annotation
  telemetry and does not establish a complete campaign cost.

Final artifacts are `campaign-summary.json`, `report.md` and
`frontier-flash-current-r2-20260908.xlsx` under the second campaign directory.

## ZSoft and deterministic verification

- Real Detect official scorer, empty submission: public format_valid=1;
  final valid=true and F1=0. Official F1 is absent from public worker feedback.
- ZSoft focused tests: 49 passed, 7 skipped, 11 subtests passed.
- Final default unittest suite: 513 tests passed.
- Full pytest before the final timeout/prompt refinements: 525 passed,
  7 skipped, 490 subtests passed. Subsequent Frontier/ZSoft focused suite:
  70 passed, 7 skipped; prompt regression: 92 passed.
- Registry check and `git diff --check` passed.
- The seven sandbox skips require unavailable `bwrap`. No ZSoft LLM,
  real L1 Docker judge or native SWE-agent run is claimed. No whole Frontier
  task matrix or native OpenEvolve campaign is claimed by this acceptance.

Later ZSoft Pi runs, local Bubblewrap installation, the real L1 differential
judge, and additional native Pi sandbox compatibility fixes are recorded in
[ZSoft Pi acceptance](2026-09-08-zsoft-pi-current-goal-plus.md). The results and
environment limitations above describe the earlier verification stage.

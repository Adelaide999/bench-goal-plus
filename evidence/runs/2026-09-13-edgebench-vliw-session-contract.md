# EdgeBench VLIW Session Contract Verification

This is a local ARM64 Pi direct verification, not an official amd64 comparison.
The Work/Judge task source is pinned to dataset revision
`47846a4c3669ad447e0ea984833b0d352460c5f9`.

## Verified Sources

- Bench: `92ceb2b`, including terminal Goal and archived report checks.
- EdgeBench: `6138fdd018e8b493ca418e2a84f77d00ef23ba07`.
- Goal Plus: `b90fb985a197cbd021f9bf36d7a31d4ab1e3feba`.
- Container GP build: `bf9909489c4ede6265d82fe26c6874f2ae4083499ab08134efa75f1891f6933e`.
- Work image: `sha256:af44629a81dc831222c3b7cbcb7d1d5046f254fb1e114c70c3586293db7ce579`.
- Judge image: `sha256:252d0f1542671a5fcbc27b5928f902752bf8334c72dcfa46fc47f9306745a28f`.
- Pi: `0.84.2`; model: `sub2api-openai/gpt-5.6-sol`; reasoning: `low`.

## Completed Campaign

Campaign: `vliw-gp-session-contract-20260913-r5`.
The public `check`, `setup`, `plan`, `launch`, `status`, and `finish` lifecycle
used profile `vliw-goal-plus-pi-sol-low-arm64-30m` with an explicit T=900-second
override. K=2, C=1, R=1; finalization grace=300 seconds. The resolved initial
worker runtime maximum was 900 seconds. Execution used API-only network access.

Both Pi sessions launched and returned exact native invocation receipts. Their
frozen verifier scores were 2178 and 2145 cycles. Main closed both sessions,
selected c002, promoted its exact artifact, and submitted it to Judge. Judge
passed 9/9 cases at 2145 cycles, with score 49.077317032202245/100.

At the exploration cutoff, the controller recorded retry admission, stopped its
owned Main, and resumed the same native session once. Finalization finished in
about 107 seconds; total agent runtime was about 1007 seconds. The Goal reached
`complete`, linked Search results were recorded, and final Markdown/HTML reports
were archived. Completion evidence passed, including the Goal/report gate.
Work container and controller-owned Judge cleanup completed.

The campaign remains under `runs/edgebench/vliw-gp-session-contract-20260913-r5/`,
with `comparison.json`, `report.md`, its XLSX workbook, and original state archive.

## Three-Round Evidence

Campaign `vliw-gp-session-contract-20260913-r4` used T=1800 and two workers, each
with three native invocations and three verifier records. The best candidate
progressed 2066 -> 1990 -> 1966 cycles; Judge passed 9/9 at 1966 cycles.
Its EdgeBench build was `e9c4489`, before the managed-Python retry fix.
Goal closeout failed because a relocated Python symlink lost its virtualenv
package path. Its corrected report is `partial`; the valid score and all six
invocation/verifier records are preserved. It is not full-lifecycle acceptance.

## Checks and Limits

Bench: 525 tests, one skipped. EdgeBench adapter/bridge slice: 60 passed.
Registry check, `git diff --check`, and affected relative file links passed.
No GP core code or process-identity supervision was added for these runs.
This record does not verify Codex, ThinkThread, other benchmark adapters, or
official amd64 equivalence. The global environment update inventory remained
blocked by missing default amd64 task images; the selected ARM64 inventory and
doctor passed independently.

# ZSoft Pi with current Goal Plus

## Sources and environment

- Goal Plus: clean external source `refactor/goal-plus-consolidated`,
  `432d1fbcc8d3f7fc0725dcc8292af65ab8cf1eaf`.
- ZSoft: managed clean `linmalin-zsoft-benchmarks-mr`,
  `7967e9e7c95d30decb19b525c9cad6533e83ff59`.
- Host: Linux aarch64; Pi 0.84.2; model `zai/glm-5.3-flash`, low reasoning.
- Bubblewrap 0.8.0 was installed under `.bench-env/bubblewrap` from Debian
  bookworm's arm64 package. Package SHA256:
  `d044ba1d7961d835669035fcd1e11121f1dc960a1a2e1c6489a93ea44e083557`.
- Docker Compose v2.39.4 was installed under `.bench-env/docker`; binary SHA256:
  `49082844b87f03cdcd5f5bbef1ba8c9c897b7a2dfb80cea18d61ec8ca6117e0c`.
- The unchanged official L1 Dockerfiles were built for arm64 using upstream
  `gcc:14-bookworm`, repo digest
  `sha256:5e927c284bf55a7dc796262e311a0703344f62f41f5621eb56843111b1d37e15`.
  Vulnerable image ID:
  `sha256:75c65e3c0f3b8072f0e976e689fa735b09b0e50e8bbc68e8f6a453ab7ac2f3e9`;
  fixed image ID:
  `sha256:70e7ee2c9ad5dc498909522ce288699d9145e4c9f545e2d855c7eb1b4ef51191`.
- Credentials were inherited and never included in this evidence. Runtime
  artifacts, Docker configuration and fetched tools are ignored local files.

## Regressions found by real workers

1. Current native Pi invokes an internal-agent kick after loading context and
   verifying. Its one-time capability file could not be written in the old
   sandbox, so context activation never completed. The launcher now gives Pi
   a private runtime and proxies only the exact bound Search kick with a
   validated single-use capability; real runtime state remains hidden.
2. In visible-feedback mode, current Pi reads the candidate generation before
   every tool. The private runtime lacked that file, producing `Search worker
   generation could not be verified.` after a successful context call. The
   proxy now validates the context identity and writes only the generation into
   a read-only subtree. A generation change within one launch is rejected.
3. L1's process verifier runs the live official judge. Its timeout now derives
   from the selected official task, with controller overhead. The sample has
   a 180-second judge timeout and 360-second process/promotion limits; tasks
   with a 900-second judge retain 1080 seconds. No official timeout is lowered.

The narrow launcher suite passes 26 tests and 9 subtests, including real
Bubblewrap visible/blind isolation, immutable generation projection, identity
rejection, native callback single use, and real Pi executable startup. These
tests do not claim end-to-end recovery support.

## Preserved initial Detect attempt

Campaign `runs/benchmark-campaigns/zsoft-detect-pi-glm53flash-20260908` used
`civetweb-detect`, T=900, K=1, C=1, R=1, worker limit 360/minimum 120 seconds,
and no shared-dir.

The first job was blocked by the native callback regression and had no
verifier. Main later continued the same candidate/session after the adapter
fix. That job verified one clean kept iteration. Goal completed and Search
promoted. Controller-only official scoring returned valid=true and
F1=0.28571428571428575 (TP=2, FP=1, FN=9). The campaign remains partial because
the first job did not meet the required verifier/minimum-lease contract. The
gate was preserved; `finish` generated the archived report.

## L1 acceptance

The initial T=900 campaign `zsoft-l1-pi-glm53flash-20260908` is preserved as
partial. Its first context succeeded but the generation guard blocked later
tools; Main ultimately became blocked with no verified candidate. Controller
closeout required host resume. It is not counted as workflow acceptance.

Fresh campaign
`runs/benchmark-campaigns/zsoft-l1-pi-glm53flash-r2-20260908` passed and was
archived through `finish`. It used `sample-asan-crash`, T=1800, K=1, C=1, R=1,
worker limit 600/minimum 120 seconds, and no shared-dir. The larger T includes
discovery and the full official verifier reservations; the task was not changed.

- Seed success=0; final official success=1, valid=true. The same submitted PoC
  caused vulnerable exit 134 and fixed exit 0. Official evaluator and cleanup
  both completed without timeout.
- Search `run_20260908_075007_6523ab5d`: one candidate, one bound session, one
  clean kept process iteration, one promotion verifier, and one controller
  final evaluation. Including setup seed, the reported total is four calls.
- Goal complete, Search promoted, source apply confirmed. Pool closed with
  active_count=0 and close_timed_out=false.
- Controlled execution took 241.869 seconds and stopped on the live success
  gate. Main received SIGTERM (143), with no deadline expiration or hard kill.
  The worker's 35-second interval was interrupted by the supervisor after its
  settled success; final official confirmation set
  `early_stop_completion_verified=true` and
  `minimum_lease_completion_waived=true`. This is the existing successful
  early-stop contract, not a relaxed failed-job gate.
- One Annotation task was cancelled before inference during closeout; this
  run does not establish completed Annotation lifecycle coverage.
- `campaign-summary.json`, `report.md` and
  `zsoft-l1-pi-glm53flash-r2-20260908.xlsx` are archived in the campaign directory.

The final ZSoft focused suite passes 52 tests and 20 subtests, with real
Bubblewrap tests enabled and no skips.

## Fresh Detect outcome

Campaign `runs/benchmark-campaigns/zsoft-detect-pi-glm53flash-r2-20260908`
used the same task, model, T=900, K=1, C=1, R=1, worker maximum 360/minimum
120 seconds, and no shared-dir. It was archived through `finish`.

- Official final F1=0.14285714285714288, valid=true, maximize. The hidden
  scorer ran once after controller closeout, with no hidden score in Search.
  The public seed's format_valid value is a different metric; the report
  therefore leaves F1 seed/gain unavailable rather than subtracting the
  public gate from the official score. A regression test covers this case.
- Search `run_20260908_075428_8556b2a5` promoted and Goal completed. Public
  selection used `lowest_candidate_id_latest_compliant_iteration`; the
  resulting artifact was applied to the scoring workspace.
- The single pool job ran from 07:54:56Z until supervisor interruption at
  08:00:37Z. Controller execution lasted 841.367 seconds, then closed the
  pool with active_count=0 and close_timed_out=false.
- Campaign remains **partial**: that interrupted job has no completed
  minimum-lease result record. Elapsed time and an existing public iteration
  do not replace the required lease evidence. The acceptance gate was not
  waived or weakened. This result does not establish completed Detect
  lifecycle coverage, and the registry does not claim that it does.

This record supersedes the earlier ZSoft environment-only limitations in
[the Frontier/ZSoft record](2026-09-08-frontier-zsoft-current-goal-plus.md).

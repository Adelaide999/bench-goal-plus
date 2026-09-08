# SWE-bench Verified ARM64 Pi workflow check

Scope: one official `sympy__sympy-16886` case with Pi Goal Plus. This is a
workflow check, not a full Verified result or a model comparison.

## Frozen inputs

- Dataset: `SWE-bench/SWE-bench_Verified`, split `test`, revision
  `91aa3ed51b709be6457e12d00300a6a596d4c6a3`.
- Official image: `swebench/sweb.eval.arm64.sympy_1776_sympy-16886:latest`.
- Image digest: `sha256:8b4c50d6a6b72c1a288a7a39fd1a1d65e6f128dd108d2a5a2e6ed0fbbdd78bc8`.
- Image ID: `sha256:a35523885a5745e8305f712f215690be249fd8e9f69aa311a5436bbb0777412f`.
- Image architecture `arm64`; Docker host `aarch64`; native execution, no QEMU.
- Image HEAD `d4e757da000351f5941b52cef02c03bca99bd1f3` and dataset base
  `c50643a49811e9fe2f4851adff4313ad46f7325e` have the same tree:
  `61d840fb805fe61a7c24b6e13f076c1bcb62aed9`.
- Official SWE-bench external source: tag `v4.1.0`, full commit
  `726c5461e2ef52d83cf1ea2107870a8bb3328d57`. Managed main remains unchanged;
  its current v5 dataset contract is incompatible with this pinned v4 row.
- Goal Plus external source: branch `refactor/goal-plus-consolidated`, full
  commit `432d1fbcc8d3f7fc0725dcc8292af65ab8cf1eaf`, clean checkout.
- Bench base `6526608`, with this uncommitted adaptation. Pi `0.84.2`;
  `zai/glm-5.3-flash`, reasoning `low`.
- T=900 seconds, K=1, C=1, R=1; Git worktree, parallel loops, no shared
  directory, Annotation disabled, no Adaptive Scheduler. Worker lease 120
  seconds, closeout reserve 120 seconds, visible wrapper timeout 60 seconds.
- Agent receives only the public task allowlist. Complete dataset rows remain
  controller-only; the official evaluator owns final `resolved`.

## Environment adaptation

The ARM image and all task dependencies are preserved. Goal Plus uses a
read-only mount of portable CPython 3.12.13 and a disposable venv, installs the
repository dependency lock, and runs the source `install.sh --pi`. The SymPy
task retains Python 3.9.21 in the image's `testbed` Conda environment. Pi model
metadata is projected from the exact host catalog entry; authentication is
inherited through `ZAI_API_KEY` and is not serialized.

Full doctor passed the image/tree, Pi model, Goal Plus installation/imports,
and official harness source checks. Launch exposed a missing doctor CLI
`--reasoning-effort` argument; this was fixed and tested before model execution.

## First trajectory

Campaign: `runs/swe-bench-verified/swe-arm-pi-glm53flash-20260908`.

- Terminal campaign/Agent state `partial`; timed out at 900.04 seconds.
- Main created an active Goal but no FrozenSpec, Search run, candidate, or
  submitted patch. Official evaluator calls: 0; no raw `resolved` value.
- Isolated Pi HOME bypassed the image's `/root/.bashrc` Conda activation.
  Bare Python could not import `mpmath`; Main eventually found the already
  installed `testbed` environment. No package installation was needed.
- The runner now activates `testbed` explicitly for Pi startup. The generated
  shell was executed inside the real ARM container with isolated HOME and
  resolved Python to `/opt/miniconda3/envs/testbed/bin/python`, importing
  existing `mpmath` 1.3.0 successfully. Goal Plus keeps its separate interpreter.
- Main then sent invalid freeze parameters: first an extra artifact-path field
  inside `spec`, then an incomplete `spec` containing only workspace settings.
  Validation rejected both. The last streamed response was still generating
  tool arguments at the outer deadline; this does not prove a hung host.
- Controller closeout correctly reported no materialized linked run. Agent
  container removal was confirmed. Public `finish` archived the partial result.
- This first campaign predates the explicit Conda activation fix. It is retained
  separately from the subsequent run; no state or transcript was rewritten.

## Second trajectory

Campaign: `runs/swe-bench-verified/swe-arm-pi-glm53flash-r2-20260908`.

- Conda activation worked; Main no longer lacked `mpmath`. It froze Search
  `run_20260908_053220_09e5bd63`, created one candidate and bound a Pi worker.
- Native Pi doctor used the projected Flash model catalog, but the actual
  trajectory bypassed that route. Main used Flash; worker catalog lookup
  rejected Flash and Main substituted `zai/glm-5.3`. This is not valid evidence
  for the requested worker model. The actual native route now uses the same
  model projection as doctor, and completion checks the selected worker model.
- The same worker had an initial launch and continuation. Both final-verifier
  attempts were refused because remaining time could not cover the frozen
  121-second verifier suite bound plus the 120-second closeout reserve.
  No candidate verifier Evidence settled; Goal Plus closeout remained partial.
- Main committed the read-only wrapper to satisfy the current frozen-source
  artifact contract. The old export included only this runner-owned file, not
  the unpromoted candidate repair. Export now excludes runner-managed paths;
  a real local Git test covers both repair-plus-assets and assets-only diffs.
- Official ARM evaluator: exactly one invocation, 26.88 seconds, return code 0,
  `patch_successfully_applied=true`, `resolved=false`. This is a valid raw
  official result, not a completed Goal Plus workflow.
- Agent and evaluator containers were removed. Public `finish` archived the
  partial campaign and preserved its original evaluator report.
- SWE completion also still read the obsolete frozen closeout config key.
  It now reads `reserve_closeout_seconds`, with regression coverage rejecting
  the obsolete key. This deterministic parser fix does not alter raw Evidence.

## Successful third trajectory

Campaign: `runs/swe-bench-verified/swe-arm-pi-glm53flash-r3-20260908`.

- Final campaign and Agent state: `completed`. Goal `gp_0001`: `complete`.
  Search `run_20260908_054958_e02e727e` selected candidate `c001`, promoted it,
  and applied publication. Controller reused the already applied publication.
- Frozen native host `pi`; backend `git_worktree`; inner agent `autoresearch`;
  `parallel_loops`, K=1. Both the frozen model and the bound worker's selected
  model are exactly `zai/glm-5.3-flash`; the model completion gate passed.
- Exactly one bound worker and one settled candidate iteration. The real Pi
  worker ran from `05:50:43Z` to `05:51:21Z`, with no job error. Visible score
  and independent promotion visible score were both 1.0.
- Main exited normally with return code 0 after 387.28 seconds, without timeout.
  Container setup took 36.85 seconds; controller finalization took 3.57 seconds.
- Official ARM evaluator: exactly one call, 26.78 seconds, return code 0,
  `patch_successfully_applied=true`, `resolved=true`.
- Public `status` and `finish` confirmed completion and exported `report.md`,
  `campaign-summary.md/json`, and the campaign-named XLSX workbook. All Goal Plus
  completion checks passed, including exact worker model and closeout reserve.
- Agent removal was confirmed. No Agent or official evaluator container for the
  ARM task image remained; the official image itself is retained.
- The final code change in the evaluated patch repairs the one incorrect Morse
  table entry in `sympy/crypto/crypto.py`. This campaign's controller was already
  running when the deterministic export exclusion was fixed, so its preserved
  raw patch also contains the runner-owned verifier file. No raw patch/report
  was rewritten. The final exclusion is covered by a real local Git regression;
  no additional LLM campaign was run solely for that deterministic export fix.
- This proves one native ARM Pi Goal Plus workflow with the stated sources and
  configuration. It does not claim full Verified, ARM Codex, or K>1 coverage.

## Reproduction

Set validated external source overrides through all lifecycle commands:

```bash
export BENCH_GOAL_PLUS_SOURCE_DIR=<clean-goal-plus-checkout>
export BENCH_GOAL_PLUS_EXPECTED_REF=refactor/goal-plus-consolidated
export BENCH_SWEBENCH_SOURCE_DIR=<clean-official-swebench-v4-checkout>
export BENCH_SWEBENCH_EXPECTED_REF=v4.1.0
```

Use profiled `check` and `setup --skip-provision`, then the same selection for
`plan` and `launch`:

```bash
python3 scripts/bench.py launch \
  --benchmark swe-bench-verified \
  --profile sympy-16886-goal-plus-pi-arm64-smoke \
  --method goal-plus-pi --model zai/glm-5.3-flash --reasoning-effort low \
  --wall-time-seconds 900 --live-search-concurrency 1 --cell-concurrency 1 \
  --campaign-id <new-id> --skip-bootstrap --skip-provision --foreground
python3 scripts/bench.py status --campaign <campaign-path>
python3 scripts/bench.py finish --campaign <campaign-path>
```

Local cache locations were set below the checkout with `XDG_CACHE_HOME` and
`HF_HOME`; they do not change the frozen dataset revision or official evaluator.

## Regression checks

- Final focused SWE suite: 65 passed. Earlier combined SWE, source-selection,
  and OpenEvolve check: 124 passed, one known unrelated blind-prompt assertion
  deselected; later SWE additions were checked by the final focused/default runs.
- Default suite: 502 tests, 5 failures and 18 errors. Remaining failures concern
  missing Frontier/ZSoft assets, existing controller/ambient-auth fixtures,
  blind-prompt and runtime-path assertions. SWE tests passed.
- Registry validation: 16 registry items and 8 datasets passed.
- `git diff --check` passed. No commit or push performed.

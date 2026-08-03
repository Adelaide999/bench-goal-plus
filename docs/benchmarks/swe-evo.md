# SWE-EVO

The executable target is `swe-evo` with the native controller at
`experiments/swe_evo/experiment.py`. Source and dataset are pinned to commit
`9b83d5af943ba7a17567336f5b18239f73960219`; the Arrow stream is independently pinned by SHA256.

The worker side deliberately reuses SForge from the tracked EdgeBench fork. This provides the same
Codex runtime injection, Goal Plus source injection, API allowlist, worker timeout/resume behavior,
and separate process-judge container already used by EdgeBench. Benchmark-specific code is limited
to dataset materialization, safe task definitions, patch freezing, and official SWE-EVO scoring.

Readiness is intentionally split: the controller and a two-task GHCR panel are executable, while the
full 48-task campaign is blocked until every exact upstream image can be pulled or mirrored on the
Linux runner. Existing standard SWE-bench images are not accepted as substitutes.

## Run on gpu77

Bootstrap the pinned checkouts and managed environment first. The smoke profiles pin both the Arrow
stream and each source-image manifest digest. A registry mirror may be used as a transport path only;
the controller refuses it when its manifest digest differs from the pinned official digest.

```bash
export SWE_EVO_IMAGE_MIRROR=ghcr.nju.edu.cn  # optional on a slow GHCR route
python scripts/bootstrap.py --target swe-evo-native
.bench-env/venv/bin/python experiments/swe_evo/experiment.py provision --profile ghcr-smoke-1
.bench-env/venv/bin/python experiments/swe_evo/experiment.py doctor --profile ghcr-smoke-1
```

Run the one-task Goal Plus smoke in the foreground:

```bash
.bench-env/venv/bin/python experiments/swe_evo/experiment.py prepare \
  --profile ghcr-smoke-1 --campaign-id swe-evo-goal-plus-smoke
.bench-env/venv/bin/python experiments/swe_evo/experiment.py run \
  --campaign swe-evo-goal-plus-smoke
```

The smoke uses `T=900`, `K=2`, `C=1`, and `R=1`. Its extra 300-second
finalization window is reserved for promotion, synchronous process judging, and the independent
official evaluator; it is not additional candidate exploration time.

`runs/swe-evo/<campaign>/comparison.json` is the machine-readable result and `comparison.md` is the
human-readable table. Only the vendored SWE-bench harness fields `resolved`, `fix_rate`, and
`patch_applied` are official. The SForge process judge checks patch integrity during search but is not
reported as the benchmark score.

## Validated smoke

The `ghcr-smoke-1` profile was run end to end on gpu77 on 2026-08-03. Goal Plus launched
two workers, recorded one verifier run for each candidate, selected and promoted `c001`, and reached
`final_audit/complete`. The official evaluator then reported `resolved=true`, `fix_rate=1.0`, and
`patch_applied=true`; the frozen patch changed only `requests/models.py` and had no hidden-test path
overlap.

The compact evidence is under
`evidence/runs/2026-08-03-swe-evo-gpu77-goal-plus-smoke/`. This validates the one-task pipeline and
does not claim that the full 48-task image panel or a matched Plain Codex comparison is complete.

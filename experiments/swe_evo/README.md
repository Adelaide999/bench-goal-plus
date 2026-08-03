# SWE-EVO native lifecycle

This integration compares Plain Codex and Goal Plus + Codex on the 48 release-evolution tasks in
SWE-EVO. It reuses EdgeBench's SForge lifecycle for worker isolation, API-only network access,
automatic agent resume, process judging, and campaign stop/status handling. Final benchmark scores
come only from SWE-EVO's vendored SWE-bench harness.

## Boundaries

- `evaluator/instances.json` is mode `0600` and contains `test_patch`, `FAIL_TO_PASS`,
  `PASS_TO_PASS`, and the upstream patch. Those fields never enter `sforge_tasks/`.
- The SForge judge checks only that a non-empty patch has a valid Git diff. Its score is explicitly
  process-only and is never reported as an official metric.
- After a worker stops, `final_archive.tar.gz` is overlaid on a fresh source image and frozen as a
  full-index binary Git patch. Patches touching hidden test-patch paths fail integrity validation.
- A second fresh container runs the native SWE-EVO evaluator and records raw `resolved`,
  `patch_applied`, and `fix_rate` results.
- Plain Codex uses K independent replicas. Its post-hoc best is labeled `oracle_best_fix_rate` and
  is not treated as equivalent to Goal Plus's in-search selected promotion.

## Profiles

| Profile | Tasks | Methods | T/K/C/R | Purpose |
|---|---:|---|---|---|
| `ghcr-smoke-1` | 1 | Goal Plus | 900/2/1/1 | Cheapest real Goal Plus lifecycle |
| `ghcr-smoke-2` | 2 | Plain + Goal Plus | 1800/2/1/1 | Matched GHCR-hosted regression |
| `full-48` | 48 | Plain + Goal Plus | 7200/4/2/1 | Full upstream panel; image readiness required |

The smoke profile is frozen because its images are available from GHCR. `development-12` remains
`selection_pending`; the 77-machine image audit does not support claiming it is ready.

## Commands

```bash
python3 scripts/bench.py check --preset swe-evo-goal-plus-smoke
python3 scripts/bench.py setup --preset swe-evo-goal-plus-smoke
python3 scripts/bench.py plan --preset swe-evo-goal-plus-smoke
python3 scripts/bench.py launch --preset swe-evo-goal-plus-smoke
```

Direct controller diagnostics:

```bash
.bench-env/venv/bin/python experiments/swe_evo/experiment.py doctor --profile ghcr-smoke-1
.bench-env/venv/bin/python experiments/swe_evo/experiment.py verify-official \
  --profile ghcr-smoke-1 --output evidence/environment/swe-evo-official-smoke.json
```

After completion, `scripts/bench.py finish --campaign <path>` exports `report.md` and XLSX from
`comparison.json`. Inspect each trajectory under `evaluator/attempts/`; official logs and raw reports
are preserved below its `official/logs/run_evaluation/` directory.

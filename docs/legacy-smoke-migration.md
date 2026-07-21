# Legacy smoke migration completion

Migration from `mythink/agentic-scaling/benchmark-smoke` completed on 2026-07-21. This repository is
now the single source of truth for benchmark integration status, executable adapters, direct-API
environment baselines, and committed smoke evidence.

## Source disposition

| Old source | New location or disposition |
|---|---|
| `README.md` | Rewritten without machine-specific paths as `docs/legacy-smoke-runbook.md` |
| `run_ale_case.py` | `legacy/direct-api/run_ale_case.py` |
| `run_ale_valid_case.py` | Parameterized as `legacy/direct-api/run_ale_valid_case.py`; its bounded starter transformation is also implemented in `adapters/ale/materialize.py` |
| `heurigym_operator_solver.py` | `legacy/direct-api/heurigym_operator_solver.py` |
| `skydiscover-evox-deepseek-smoke.yaml` | `legacy/direct-api/skydiscover-evox-deepseek-smoke.yaml` |
| `verify_smokes.py` | Replaced by `scripts/verify_legacy_smokes.py`, which checks committed evidence and can cross-check remaining upstream raw runs |
| `smoke-results.json` | `evidence/legacy-smokes/source-smoke-results.json` |
| ALE and HeuriGym deterministic results | `evidence/legacy-smokes/ale-ahc027-valid-baseline.json` and `heurigym-operator-scheduling-demo.output` |
| SkyDiscover best/checkpoint/program records | Full tree under `evidence/legacy-smokes/skydiscover-evox-circle-deepseek-1iter-20260720/` |
| SkyDiscover raw log | Sanitized and renamed to `logs/evox_20260720_035607.log.txt` so it is tracked |
| Python bytecode cache | Deliberately discarded; generated, non-reproducibility data |
| Empty `search/` directory | Deliberately discarded; contained no data |

AutoLab's small official reward was already migrated to
`evidence/legacy-smokes/autolab-toy-isa-reward.json`. Large transient Docker/build state is not part
of the benchmark logic and remains reproducible from the runbook.

## Deletion gate

The old directory is safe to delete when all of the following pass on the committed revision:

```bash
python3 scripts/verify_legacy_smokes.py --upstreams-root ..
python3 scripts/status.py --check
python3 -m unittest discover -s tests -v
git diff --check
```

No future experiment may write to the old path. New raw runs go to the gitignored `runs/` directory;
small reviewed evidence is promoted into `evidence/` and referenced from `benchmarks/registry.json`.

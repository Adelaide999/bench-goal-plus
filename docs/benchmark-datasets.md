# Benchmark dataset and panel catalog

`benchmarks/datasets.json` records candidate datasets separately from executable
task adapters and benchmark integration status. It follows the staged selection
in `goal-plus-benchmark-scenarios(1).md` without vendoring upstream repositories,
task archives, browser state, or container images.

## Why this is a separate catalog

The repository now has three deliberately different registries:

| File | Owns | Does not imply |
|---|---|---|
| `benchmarks/registry.json` | Integration gates and reproducible evidence | That every benchmark has a generic adapter |
| `benchmarks/datasets.json` | Dataset provenance, experiment role, and panels | That a panel can already execute |
| `benchmarks/task-adapters.json` | Importable single-artifact adapter modules | Support for browser, repository-service, or security environments |

A heavy dataset must not be added to `task-adapters.json` until its native lane,
observer, reset, and final judge are implemented. This prevents a catalog entry
from being mistaken for an end-to-end benchmark result.

## Current datasets

| Dataset | Domain | Tasks | Role | First panel |
|---|---|---:|---|---|
| SWE-EVO | Software evolution | 48 | Primary | `development-12` |
| RoadmapBench | Long-horizon software | 115 | Confirmatory | `selected-20` |
| SWE-bench Pro audited subset | Software repair | 731 public candidates | Audit required | `audited-clean` |
| SWE-bench Verified | Software repair | 500 | Smoke only | `smoke-10` |
| Cybench | Security investigation | 40 | Mechanism | `full-40` |
| CyberGym | Vulnerability reproduction | 1,507 | Primary | `official-smoke-10` |
| WebArena | Stateful web interaction | 812 | Mechanism | `mechanism-50` |
| WorkArena L1 | Enterprise web interaction | 330 | Mechanism | `mechanism-50` |

The CyberGym `official-smoke-10` entry contains the ten task IDs published by
the upstream subset downloader. Proposed SWE-EVO 12-task, CyberGym 75/300-task,
and browser 50-task panels remain `selection_pending`; their IDs must be
published after environment and difficulty audits.

## Panel states

| State | Meaning |
|---|---|
| `selection_pending` | Target size and selection rule exist, but task IDs are not fixed |
| `upstream_defined` | Upstream defines the split or subset, but this repository has not pinned all revisions |
| `frozen` | Source revision and every task ID are explicit and validated |

The validator rejects a `frozen` panel without both a source revision and an
explicit task list. It also rejects duplicate IDs and task-count mismatches.

## Inspect the catalog

```bash
python3 scripts/datasets.py validate
python3 scripts/datasets.py list
python3 scripts/datasets.py list --domain software --stage 1
python3 scripts/datasets.py show swe-evo
.bench-env/venv/bin/python scripts/status.py --check
```

`--stage` follows the scenario plan:

| Stage | Use |
|---:|---|
| 0 | Environment, reset, logging, and verifier shakedown |
| 1 | Model/task signal calibration |
| 2 | Main B0/B1/B3/B4 mechanism experiment |
| 3 | Stronger-model confirmation on selected tasks |
| 4 | Full or long-running protocol |

## Path to execution

Each non-artifact dataset needs a native adapter with the same control-plane
outputs as the current campaign, but not the same workspace implementation:

1. Pin repository, dataset, service, image, and evaluator revisions.
2. Freeze a panel by committing task IDs and selection evidence.
3. Implement a fixed number of resettable environment lanes.
4. Emit task observations, actions, verifier calls, usage, and wall-time events.
5. Run the parent-owned final judge and preserve the native raw metrics.
6. Add campaign collection and B0/B1/B3/B4 condition mapping only after a
   model-free seed or environment smoke passes.

Recommended implementation order is BrowserGym WebArena/WorkArena, SWE-EVO,
Cybench, then CyberGym. RoadmapBench remains source-blocked. SWE-bench Pro must
retain per-task audit decisions, and SWE-bench Verified is restricted to smoke
and regression use.

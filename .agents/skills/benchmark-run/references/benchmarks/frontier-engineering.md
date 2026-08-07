# Frontier-Engineering native runner

Target `frontier-engineering` preserves the upstream `v1_lite.yaml` task
contracts and UnifiedTask evaluator. Its default `v1-lite-cpu-codex-1h`
profile excludes the CUDA-backed RobotArm task and runs 9 CPU tasks. The full
`v1-lite-codex-1h` profile preserves all 10 tasks but declares
`nvidia-cuda-opt-in`; its doctor must pass `nvidia-smi` and the selected
runtime's PyTorch CUDA probe before evaluating a seed. The legacy target
`frontier-engineering-malloclab` is only a portable one-task regression.

## Completion and evidence

- A cell is complete only when its controller-owned final evaluator returns a
  valid upstream `combined_score` and the selected Agent lane exits cleanly.
- Raw `metrics.json` and `artifacts.json` remain attached to each evaluator
  event; `combined_score` is maximize.
- Goal Plus cells additionally require actual worker/subagent evidence equal to
  `K`; missing evidence keeps the cell and campaign `partial`.
- Plain Pi uses `K` isolated outer Pi lanes. Both Pi methods require the
  profile model to be visible through the run-local OpenAI-compatible Pi
  provider configured from `OPENAI_BASE_URL` and `OPENAI_API_KEY`; values are
  inherited and never written to campaign manifests or reports.
- Final source is `campaign-summary.json`; `finish` exports `report.md` and the
  campaign-named XLSX.

## Lifecycle

The target supports native provision, detached execution, stop, and finalization.
It does not resume the same trajectory. A stopped campaign is finalized as
`partial`; a retry uses a new campaign ID.

`K` is task-internal Agent concurrency. `C` is currently fixed to one because
several v1-lite evaluators are timing- or GPU-sensitive. Do not map Hydra batch
`max_parallel` to `K`.

Before setup, run the profile inventory. Provision creates only the three uv
runtimes used by v1-lite (`frontier-eval-driver`, `frontier-v1-main`, and
`frontier-v1-summit`); it does not install host packages or unrelated v1 assets.
The EnergyStorage acceptance profiles freeze `K=1, C=1, R=1`; Plain Pi uses
`T=300`, while Goal Plus + Pi uses the exercised `T=600` closeout budget.

# Frontier-Engineering v1-lite native controller

This controller preserves the upstream `v1_lite.yaml` task contracts and its
`UnifiedTask` evaluators. The default profile contains the 9 CPU tasks; the
full 10-task profile explicitly opts into NVIDIA CUDA for RobotArm and is
blocked by doctor unless both the driver and runtime CUDA probes pass. It owns campaign state only; benchmark runtimes,
candidate sandboxing, raw `metrics.json`, and `artifacts.json` remain upstream.

The registered lifecycle is:

```bash
python3 scripts/bench.py check --preset frontier-engineering-energy-storage-codex-smoke
python3 scripts/bench.py setup --preset frontier-engineering-energy-storage-codex-smoke
python3 scripts/bench.py plan --preset frontier-engineering-energy-storage-codex-smoke
python3 scripts/bench.py launch --preset frontier-engineering-energy-storage-codex-smoke --campaign-id <id>
python3 scripts/bench.py status --campaign runs/frontier-engineering/<id>
python3 scripts/bench.py finish --campaign runs/frontier-engineering/<id>
```

The EnergyStorage preset is the primary acceptance smoke: its editable policy is
small, its shipped candidate is feasible, and its official evaluator is fast
enough for repeated feedback inside a five-minute Agent budget. The JobShop
preset remains available as a slower scheduling regression.

`K` is implemented by the selected method inside one task cell. `C` remains
restricted to one until cross-task resource isolation has separate evidence.
The legacy `frontier-engineering-malloclab` common target remains a fast portable
regression and is not the v1-lite campaign target.

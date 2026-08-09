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

The Plain Pi and Goal Plus + Pi acceptance presets use the same EnergyStorage
task with `K=1, C=1, R=1`. Plain Pi uses `T=300` and starts one isolated outer
lane. Goal Plus + Pi uses the exercised `T=600` budget and starts one outer Pi
session whose one internal worker shares the Goal Plus Search state.

The EnergyStorage preset is the primary acceptance smoke: its editable policy is
small, its shipped candidate is feasible, and its official evaluator is fast
enough for repeated feedback inside a five-minute Agent budget. The JobShop
preset remains available as a slower scheduling regression.

`K` is implemented by the selected method inside one task cell. `C` remains
restricted to one until cross-task resource isolation has separate evidence.
The legacy `frontier-engineering-malloclab` common target remains a fast portable
regression and is not the v1-lite campaign target.

The `frontier-engineering-energy-storage-openevolve-paper-100` preset preserves
the upstream Experiment 1 search protocol on the same EnergyStorage task. It
uses the shipped initial program, frozen UnifiedTask verifier, OpenEvolve 0.2.26
defaults, temperature 0.7, and 100 evolution iterations. The 12-hour wall value
is a fail-safe ceiling rather than the selection budget. Completion requires an
audited initial-program record, exactly 100 evolved candidates, and a valid
controller final evaluation.

The `frontier-engineering-energy-storage-openevolve-smoke-5` preset exercises
the same initial program, verifier, model configuration, and OpenEvolve search
path with five evolution iterations. It is diagnostic rather than a paper
result. Completion requires one initial-program record, exactly five evolved
candidates, a saved best program, and a valid controller final evaluation.

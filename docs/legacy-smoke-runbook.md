# Legacy direct-API smoke runbook

This runbook preserves the commands used before benchmark work moved into this repository. These
paths assume `bench-goal-plus`, `ALE-Bench`, `HeuriGym`, `AutoLab`, and `skydiscover` are sibling
checkouts under one directory.

Credentials must be injected through environment variables. Never save a real key in a config,
command transcript, evidence file, or Git commit.

## ALE-Bench Lite

Generate one `ahc027` candidate through the original model API path:

```bash
cd ALE-Bench
export DOCKER_HOST="unix://${HOME}/.orbstack/run/docker.sock"
export ANTHROPIC_BASE_URL=https://api.deepseek.com/anthropic
export ANTHROPIC_API_KEY='...'

.venv/bin/python ../bench-goal-plus/legacy/direct-api/run_ale_case.py \
  --problem-id ahc027 \
  --model-config llm_configs/deepseek-v4-flash-anthropic-local.json \
  --output .tmp/e2e-smoke/ale-deepseek-v4-flash
```

Re-score the same generated artifact after disabling its known optional unbounded local-search
loop. This is a deterministic environment/verifier smoke, not a model-quality result:

```bash
.venv/bin/python ../bench-goal-plus/legacy/direct-api/run_ale_valid_case.py \
  --source-results .tmp/e2e-smoke/ale-deepseek-v4-flash/ahc027/results/final_results.json \
  --output .tmp/e2e-smoke/ale-deepseek-v4-flash/ahc027/valid-baseline.json
```

The migrated result is
`evidence/legacy-smokes/ale-ahc027-valid-baseline.json`. New Codex experiments use
`adapters/ale/`, not these direct-API wrappers.

## HeuriGym

The original one-shot model command was:

```bash
cd HeuriGym
export DEEPSEEK_API_KEY='...'
export DEEPSEEK_BASE_URL=https://api.deepseek.com/v1
export HEURIGYM_MAX_TOKENS=32768

.venv/bin/python llm_solver_agent.py \
  --models deepseek-v4-flash \
  --iterations 1 \
  --problem operator_scheduling \
  --timeout 10 \
  --num_cores 4 \
  --few_shots 1
```

The deterministic verifier smoke is independent of the invalid model first draft:

```bash
.venv/bin/python ../bench-goal-plus/legacy/direct-api/heurigym_operator_solver.py \
  _datasets/operator_scheduling/demo/demo.json \
  .tmp/heurigym-operator-scheduling-demo.output
```

The accepted output is stored at
`evidence/legacy-smokes/heurigym-operator-scheduling-demo.output`.

## AutoLab

The bounded `toy_isa_opt` smoke used a remote model while the Mac ran Harbor, Docker, and the
official verifier:

```bash
cd AutoLab
export DOCKER_HOST="unix://${HOME}/.orbstack/run/docker.sock"
export ANTHROPIC_API_KEY='...'

.venv/bin/harbor run \
  -p tasks/toy_isa_opt \
  -a terminus-2 \
  -m anthropic/deepseek-v4-flash \
  --ak api_base=https://api.deepseek.com/anthropic \
  --ak max_turns=12 \
  --ak temperature=0.0 \
  --agent-timeout-multiplier 0.05 \
  --verifier-timeout-multiplier 1.0 \
  --environment-build-timeout-multiplier 1.0 \
  --agent-setup-timeout-multiplier 1.0 \
  -n 1 \
  --job-name e2e-deepseek-toy-isa \
  --jobs-dir .tmp/jobs \
  --yes
```

The migrated official reward is `evidence/legacy-smokes/autolab-toy-isa-reward.json`.

## SkyDiscover / EvoX

Circle packing needs NumPy but not the full math extra:

```bash
cd skydiscover
uv sync --python python3.11
export DEEPSEEK_API_KEY='...'

uv run skydiscover-run \
  benchmarks/math/circle_packing/initial_program.py \
  benchmarks/math/circle_packing/evaluator.py \
  --config ../bench-goal-plus/legacy/direct-api/skydiscover-evox-deepseek-smoke.yaml \
  --search evox \
  --model deepseek/deepseek-v4-flash \
  --api-base https://api.deepseek.com \
  --iterations 1 \
  --output ../bench-goal-plus/runs/skydiscover-evox-circle-deepseek-1iter
```

`search.share_llm: true` is required to use the selected model for both solution and search-strategy
evolution. The one-iteration run made one variation-operator request and three candidate attempts;
it did not trigger strategy hot-swap and is not paper-comparable.

The complete sanitized checkpoint, two program records, best program, and log are under
`evidence/legacy-smokes/skydiscover-evox-circle-deepseek-1iter-20260720/`.

## Evidence verification

Verify only committed evidence:

```bash
cd bench-goal-plus
python3 scripts/verify_legacy_smokes.py
```

If the three original upstream checkouts and their raw run directories still exist, cross-check
them as well:

```bash
python3 scripts/verify_legacy_smokes.py --upstreams-root ..
```

# New benchmark adaptation checklist

## 1. Intake

- Identify official repository/license, task source, evaluator owner, artifact type, metric/direction, dataset revision, system software, services/containers, network and secrets.
- Decide whether the source is executable and redistributable. Keep unavailable items catalog-only.

## 2. Reproducible environment

- Create/use a separate fork and explicit tracking branch.
- Add matching entries to `benchmarks/registry.json` and `environment/upstreams.json`.
- Declare `docker_requirement` as `required`, `mixed`, `not_required`, or `unavailable`; make `docker_scope` operationally precise.
- Route all controller/build/test scratch through `bench_runtime_paths.py` into repository-local `.tmp/`.

## 3. Execution shape

- Use the common adapter only for an isolated workspace with a clear editable artifact and controller-owned evaluator.
- Implement the adapter registry contract used by `adapters/registry.py`: materialize task, evaluate workspace, expose metadata/manifest contract, and preserve raw metrics.
- Keep a native harness when it owns service reset, browser state, work/judge containers, hidden evaluation, or specialized scheduling. Add a thin campaign wrapper instead.
- Register the executable target in `benchmarks/runners.json`. Reuse a supported runner or add one tested `BenchmarkRunner` implementation when the lifecycle differs; do not add target-name branches or a fixed launcher script.
- Choose Docker ownership: native harness is `runner`; adapter hooks/evaluator are `adapter`; a truly host-only path is `host`. For eager adapter ownership implement `provision_environment(upstream_root)` and `doctor_environment(upstream_root)`.
- Verify `plan`, prepare-created `agent-run.json`, status normalization, capability failures, final source JSON, Markdown, and XLSX.

## 4. Concurrency

- Define `T/K/C/R` using `$benchmark-run`'s concurrency contract.
- Prove process/container counts at `K=1` and `K=2`; cap shared judge/service concurrency separately.
- Keep Plain lanes isolated. Goal Plus sharing occurs only inside its frozen Search run.

## 5. Evidence and reports

- Persist resolved source commit, task/evaluator identity, commands without secrets, native score/direction, wall time, calls/tokens with coverage, and terminal/incomplete reason.
- Ensure `scripts/benchmark_report.py` can consume the final JSON shape or add a normalization path plus tests.

## 6. Gates

- Unit-test registry schema, adapter contract, materialization, evaluator parsing, concurrency bounds, failure preservation, and report row mapping.
- Run a model-free seed smoke.
- Run the smallest real official verifier smoke.
- Separately record the five support claims; no executed evidence means at most `partial`.

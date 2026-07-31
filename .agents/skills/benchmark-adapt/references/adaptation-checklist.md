# Benchmark and method adaptation checklist

## 1. Intake

- Identify official repository/license, task source, evaluator owner, artifact type, metric/direction, dataset revision, system software, services/containers, network and secrets.
- Classify the change as a new benchmark/task family or a new method/provider/auth path on an existing runner. Do not scaffold the latter as a second benchmark.
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
- Register every canonical method in `supported_methods`. Add `method_contracts` when a method requires structured input such as exact `PROVIDER/MODEL`, and reject malformed input during `plan` before setup or preparation.
- Choose Docker ownership: native harness is `runner`; adapter hooks/evaluator are `adapter`; a truly host-only path is `host`. For eager adapter ownership implement `provision_environment(upstream_root)` and `doctor_environment(upstream_root)`.
- Verify `plan`, prepare-created `agent-run.json`, status normalization, capability failures, final source JSON, Markdown, and XLSX.

## 4. Provider and authentication paths

- Treat OAuth, explicit API credentials, provider registry entries, and wire API selection as separate execution contracts even when they share one agent implementation.
- Resolve provider/model, endpoint, auth mode, credential reference, and wire API once; prove that `plan`, doctor, prepare, and launch preserve the same values without persisting secrets.
- Use one host-neutral adapter for macOS and Linux. Declare genuine host/container differences explicitly and keep unexercised platforms `partial`.
- Exercise supported Anthropic-compatible and OpenAI-compatible wire APIs through the same method when the provider registry selects the protocol; do not create protocol aliases without a distinct lifecycle.
- Remove obsolete method/provider aliases unless they are an explicit public compatibility contract, and add a negative test proving removed aliases fail closed.

## 5. Concurrency

- Define `T/K/C/R` using `$benchmark-run`'s concurrency contract.
- Prove process/container counts at `K=1` and `K=2`; cap shared judge/service concurrency separately.
- Keep Plain lanes isolated. Goal Plus sharing occurs only inside its frozen Search run.

## 6. Evidence and reports

- Persist resolved source commit, task/evaluator identity, commands without secrets, native score/direction, wall time, calls/tokens with coverage, and terminal/incomplete reason.
- Ensure `scripts/benchmark_report.py` can consume the final JSON shape or add a normalization path plus tests.
- Record official verifier readiness and every declared `supported_methods` entry separately. Split rows when auth/provider paths differ, even if they share an agent family.

## 7. Gates

- Unit-test registry schema, method contracts, adapter contract, materialization, evaluator parsing, auth/wire resolution, concurrency bounds, failure preservation, and report row mapping.
- Run a model-free seed smoke.
- Run the smallest real official verifier smoke.
- Run a host/platform smoke for every claimed supported environment, or leave the untested environment `partial`.
- No executed evidence means at most `partial`.

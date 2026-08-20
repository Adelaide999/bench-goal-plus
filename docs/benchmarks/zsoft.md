# ZSoft vulnerability benchmarks

The repository exposes two ZSoft tracks through the common benchmark adapter
contract. Both use the benchmark-owned scorer or judge; Goal Plus never replaces
the official metric with an LLM rubric.

## ZSoft Detect

The representative task is `civetweb-detect`. Preparation checks out the pinned
project revision, exports only the public benchmark contract, and creates an
empty `submission/` directory. Agents write one schema-valid JSON finding per
file. The official deterministic scorer returns precision, recall, F1, TP, FP,
and FN. Campaign selection maximizes F1, while the complete score payload is
retained for analysis.

Detect uses a directory artifact, so the common runner permits multiple changed
files inside `submission/`. The benchmark repository commit and audited project
revision are recorded separately.

## ZSoft L1

The representative task is `sample-asan-crash`. Preparation exports the public
task bundle and a single `poc` artifact. The benchmark-owned Docker differential
judge evaluates the same submission against vulnerable and fixed builds. The
native metric is binary `success`; it is not averaged with Detect F1.

## Run

Bootstrap the sparse ZSoft and Goal Plus checkouts, then use the common campaign
controller with `--benchmarks zsoft-detect` or `--benchmarks zsoft-l1`. Docker is
mandatory for L1 and is not required by the common Detect scorer. Credentials,
provider URLs, campaign outputs, and fetched source trees are not repository
artifacts and must not be committed.

Select a non-default Detect project with `--task-id`, for example
`--benchmarks zsoft-detect --task-id libxml2-detect`. A task selector applies to
exactly one benchmark and is persisted in both the campaign and cell manifests.

Adapter-level smoke tests:

```bash
python3 -m unittest \
  tests.test_zsoft_detect_adapter \
  tests.test_zsoft_l1_adapter
```

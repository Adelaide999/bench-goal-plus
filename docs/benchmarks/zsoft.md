# ZSoft vulnerability benchmarks

The repository exposes two ZSoft tracks through the common benchmark adapter
contract, plus a dedicated native SWE-agent execution target for Detect. All
paths use the benchmark-owned scorer or judge; Goal Plus never replaces the
official metric with an LLM rubric.

Both adapters follow the source MR branch
`https://gitcode.com/linmalin/muyuan-sec.git` /
`linmalin-zsoft-benchmarks-mr`. The environment manifest sparse-checks out only
the two benchmark directories and records the resolved commit in each campaign.

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

### Native SWE-agent path

`zsoft-detect-swe-agent` is a separate executable target backed by runner
`zsoft-detect-native`. Its only method is `zsoft-swe-agent`, which delegates to
the upstream `runners/launch.py swe-agent` implementation. It pins SWE-agent
1.0.1 commit `6aff2155…`, SWE-ReX 1.4.0, LiteLLM 1.93.0, the upstream prompt and
config, Bubblewrap source isolation, host-side metered proxy, and exact
provider usage. OpenCode and xiaoO are deliberately not registered.

This path requires native Linux with Bubblewrap; OrbStack Docker on macOS is
not equivalent. Its `check --profile` command is read-only and reports the
exact clean SWE-agent and audited-source revisions. Full doctor additionally
requires `OPENAI_COMPAT_BASE_URL`, `OPENAI_COMPAT_API_KEY`, and optionally a
JSON-object `OPENAI_COMPAT_HEADERS_JSON`; values are never persisted.

The initial preset is `zsoft-detect-civetweb-swe-agent-smoke`, freezing
`T=300`, `K=1`, `C=1`, and `R=1`. A run is accepted only when the upstream
launcher completes, exact usage is complete, and the deterministic scorer
returns F1 plus TP/FP/FN. Missing evidence keeps the result `partial`.
The upstream launcher has no explicit reasoning-effort option, so this native
baseline is not eligible for reasoning-matched comparisons even after a
successful run; the recorded profile label is provenance, not an applied knob.

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

For the native Detect baseline, use only the unified preset lifecycle:

```bash
python3 scripts/bench.py check --preset zsoft-detect-civetweb-swe-agent-smoke
python3 scripts/bench.py setup --preset zsoft-detect-civetweb-swe-agent-smoke
python3 scripts/bench.py plan --preset zsoft-detect-civetweb-swe-agent-smoke
```

Provision is permitted only after the read-only inventory reports exact
missing assets and acquisition is explicitly requested.

Select a non-default Detect project with `--task-id`, for example
`--benchmarks zsoft-detect --task-id libxml2-detect`. A task selector applies to
exactly one benchmark and is persisted in both the campaign and cell manifests.

Adapter-level smoke tests:

```bash
python3 -m unittest \
  tests.test_zsoft_detect_adapter \
  tests.test_zsoft_l1_adapter
```

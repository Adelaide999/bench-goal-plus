# Standalone benchmark Codex / Goal Plus wiring evidence

This record closes the first real-model E2E pass for every currently portable
standalone adapter. It proves launch, evaluator, candidate binding, promotion,
and final artifact handling. It is not a method leaderboard: the wiring budgets
are task-specific, the Plain/Goal budgets are not yet matched, and Frontier-CS
has a clock-seeded candidate.

| Benchmark / case | Seed | Plain Codex | Goal Plus + Codex | Wiring result |
|---|---:|---:|---:|---|
| ALE-Bench Lite / `ahc027` (min) | 55,181,186 | historical `gpt-5.4-mini`: 55,181,186 | `T=480,K=2`: **52,693,209**, 2/2 bound and verified, 9 iterations, 12 calls | Goal path pass; Plain reference is not matched |
| AutoLab / `toy_isa_opt` (min) | 9,220 | `T=240,K=2`: **1,547**, 8 calls | `T=360,K=2`: **9,220**, 2 bound, 1 worker verified, 5 iterations | both paths pass; not a ranking |
| Frontier-Engineering / MallocLab (max) | 28 | `T=300,K=2`: **90**, 18 calls | `T=420,K=2`: **89**, 2/2 bound and verified, 8 iterations | both pass 11/11 traces; not matched |
| Frontier-CS / problem 0 (max) | about 92.8-93.1 | `T=180,K=2`: **93.4561753**, 12 calls | `T=420,K=2`: search best 93.3980341; promotion 93.2217282; independent final **93.3097979**, 10 calls | both paths pass; score drift is expected noise |
| HeuriGym / operator scheduling (min) | 138 | `T=300,K=2`: **62** | `T=300,K=2`: **95**, 2 bound, 1 worker verified | existing E2E evidence retained |

## What changed in the reusable harness

- All benchmark/search upstreams now default to ignored `third_party/` paths
  pinned by `environment/upstreams.json`; run workspaces remain under ignored
  `runs/`.
- One runner accepts five benchmark IDs while each adapter keeps its own
  artifact, official/raw metric, direction, timeout, and host requirements.
- Goal Plus starts from a natural timed `/goal-plus` prompt with no pre-created
  `.gp`; seed/final controller runtime is external to the candidate Git tree.
- Docker-backed ALE and Frontier-CS runs explicitly use Codex
  `danger-full-access`, because `workspace-write` cannot reach the host Docker
  socket. Other adapters remain `workspace-write`.
- Frontier-CS copies any disposable candidate into a unique, ignored,
  container-visible staging directory before compile/check. This is required
  for Goal Plus freeze preflight, whose source copy lives outside the repo.
- Final selection rejects an all-invalid Plain lane set. Goal Plus completion
  requires bound sessions and at least one worker-submitted verifier result.

## Accounting limits

The table reports actual wall budgets, concurrency, verifier iterations where
available, and evaluator calls. Most deadline-terminated Codex runs have no
terminal usage event, so exact tokens and monetary cost are unavailable. The
AutoLab Goal run also predates the latest command-log telemetry schema. These
gaps are explicit; they are not treated as zero usage.

For paper-ready comparison, rerun each chosen task with one matched `T/K/model`
protocol, archive complete usage telemetry, and repeat noisy final evaluators.
Use the JSON companion for hashes and exact machine-readable fields.

## Evidence pointers

- Machine-readable companion: `2026-07-23-standalone-benchmark-codex-goal-plus.json`
- Unified checkout doctor: `../environment/2026-07-23-unified-third-party-doctor.json`
- HeuriGym detailed E2E: `2026-07-22-heurigym-operator-scheduling-codex-goal-plus.json`
- ALE historical Plain run: `2026-07-21-ale-ahc027-plain-codex/summary.json`

No API key, credential, provider header, or local absolute home path is stored
in either evidence artifact.

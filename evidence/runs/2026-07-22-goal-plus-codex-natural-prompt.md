# Goal Plus + Codex natural-prompt E2E

This run verifies the standard experiment entrypoint rather than the older controller-prepared Search-stage diagnostic.

## Contract

- Task: OpenEvolve `function_minimization`
- Method: `goal-plus-codex`
- Model: `gpt-5.6-sol`, reasoning `high`
- Provider: native Codex authentication; no direct LLM API endpoint injected
- Budget: `T=300s`, `K=2`, 60-second closeout reserve
- Prompt transform: byte-identical common task prompt, with only `/goal-plus mode=autonomous` prepended and the complete Goal Plus configuration appended
- Common-prompt SHA-256: `457492856e3cc3f3c5cf0320f13598b704c7bbd6559381436b8bcae0b7d704dd`
- Final Goal Plus prompt SHA-256: `37087dec76f2386b38b1ca54b5f71afc18d7879354d20d75b8d59116f0922d21`
- T0 invariant: `.gp/` did not exist after `prepare`; Goal, triage, frozen spec, Search run, candidates, and sessions were created by the timed Codex invocation

## Result

| Item | Observed |
|---|---:|
| Wall time | 300.044 s |
| Deadline reached | yes; graceful `SIGTERM`, no hard kill |
| Naturally created Goal | `gp_0001`, complete |
| Successful Search run | 2 candidates, 2 Codex worker sessions |
| Worker evidence | both sessions completed and each submitted a verifier result |
| Durable verifier iterations | 3 |
| Evaluator calls | 7 total: 1 setup, 6 timed plus closeout |
| Seed `combined_score` | 1.1191758447 |
| Final `combined_score` | 1.4995399671 |
| Relative improvement | +33.99% |
| Selected candidate | `c002` |
| Promotion | non-empty patch applied; Markdown and HTML reports generated |

The two workers produced distinct global-to-local optimization implementations. The controller reverified both, selected `c002`, and the common final evaluator reproduced the selected score.

## Runtime findings

The suffix now pins `strategy.name="agent_guided"`, `parallel_loops`, Codex worker host/model, `workspace.backend="copy"`, metric/verifiers, edit surface, and the outer budget. This produced one natural Goal and one Search run; there was no controller-prepared state or aborted predecessor run.

An earlier diagnostic prompt allowed the parent to duplicate a worker's process-verifier call during worker closeout, which could race the runtime-owned `results.tsv` ledger. The final prompt makes the ownership explicit: each worker submits its own process result; after all workers return, the parent selects and lets the promotion verifier perform the final gate. The final run followed that sequence and completed selection, promotion, reporting, and the common final evaluation without a ledger mutation.

Codex worker handles in this host path expose stable `task_name` values and completion handoffs but do not expose a separate `external_id`. Worker execution is therefore established by session completion metadata plus worker-owned verifier counters, not by requiring a non-null external ID. Both candidate sessions had `verifier_runs=1` and completed handoffs in this run.

## Reproduction

```bash
.bench-env/venv/bin/python experiments/openevolve_compare/experiment.py prepare \
  --method goal-plus-codex \
  --task-id function_minimization \
  --wall-time-seconds 300 \
  --concurrency 2 \
  --model gpt-5.6-sol \
  --seed 6 \
  --run-dir runs/openevolve-compare/<run-id>

.bench-env/venv/bin/python experiments/openevolve_compare/experiment.py run \
  --run-dir runs/openevolve-compare/<run-id> \
  --model gpt-5.6-sol
```

Omitting `--api-base` intentionally uses native Codex auth. The ignored run directory contains `prompt.md`, `events.jsonl`, `experiment.json`, `seed-eval.json`, `final-eval.json`, the selected artifact, and run-local `workspace/.gp/` evidence.

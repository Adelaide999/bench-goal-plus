# SWE-bench Verified native lifecycle

This controller keeps the official SWE-bench harness as the final evaluator while exposing the
repository lifecycle through `python3 scripts/bench.py`.

## Initial scope

| Contract | Frozen value |
| --- | --- |
| Dataset | `SWE-bench/SWE-bench_Verified` at `91aa3ed51b709be6457e12d00300a6a596d4c6a3` |
| Instance | `sympy__sympy-16886` |
| Image | `swebench/sweb.eval.x86_64.sympy_1776_sympy-16886:latest` |
| Methods | `plain-codex`, `plain-pi`, `goal-plus-pi` |
| Budget | `T=1800`, `K=1`, `C=1`, `R=1` |
| Metric | official `resolved`, maximize |
| Codex auth | `OPENAI_BASE_URL` + `OPENAI_API_KEY`, OpenAI-compatible Responses |

Detached execution, stop/resume, `K>1`, `C>1`, and automatic image provisioning are not supported
by this initial acceptance path. Plain Codex, Plain Pi, and Goal Plus + Pi at `K=1,C=1` passed
archived Linux/amd64 official-harness smokes under `evidence/runs/`; this does not extend the claim
to other topologies or the full Verified split. The two Plain development smokes retain their
dirty-at-prepare provenance and later acceptance commit explicitly.

## Isolation boundary

`prepare` loads the pinned dataset row and stores the complete instance only in the ignored host
campaign as the official-loader-compatible array `evaluator/instances.json` with mode `0600`. The Agent receives an allowlisted task
file containing the issue statement and public repository identity; gold patches and official test
lists are excluded.

The Agent works in a fresh container created from the exact task image. Its only output is a binary,
full-index Git diff. By default the controller confirms removal of that container before invoking the
official harness in a separate evaluation container. With unified `--retain-containers` debug mode,
it instead confirms the Agent container is stopped, records its name/ID, and leaves it available for
inspection. An evaluator attempt is persisted before the harness starts, so the same campaign cannot
silently call it twice.

Plain Codex never mounts the host OAuth file. The profile selects the same explicit custom provider
used by the repository's other direct-API Codex paths. On Linux, a loopback base URL is exposed to
the task container through the shared `systemd-socket-proxyd` bridge; setup verifies both host and
container `POST /responses` before a campaign can start.

Goal Plus + Pi starts one outer Pi JSON session through the project extension, then requires one
candidate-bound `pi-rpc` worker in the shared Search state. Its frozen SearchSpec uses only an
Agent-selected visible test command wrapped by the repository-owned numeric verifier. The wrapper
does not read hidden dataset fields and is not the official score. On completion or timeout, the
controller closes Pi pools, performs idempotent select/promote/apply closeout, exports `.gp` into the
campaign, and only then disposes the Agent container. The separate official harness remains the sole
owner of `resolved`.

The Luna Goal Plus profiles also run an independent Codex ViewAgent for every persisted candidate
iteration. It writes a concise evidence description into the Goal Plus Global Evidence View. In the
Acceptance View ON profile, MainAgent must additionally freeze 3–8 task-specific soft criteria
derived from the public issue and repository; ViewAgent reports each criterion as `covered`,
`partial`, `missing`, `unknown`, or `not_applicable`, with confidence and evidence. These labels have
no aggregate score and never affect the official binary `resolved` result. The OFF profile runs the
same ViewAgent and records descriptions but freezes no Acceptance View, keeping the model, provider,
prompt, budget, and annotation overhead matched apart from the mechanism switch.

During controller closeout, any ViewAgent work already queued by verifier-settled Evidence is drained
before `search_select`. This preserves the search-period feedback contract for the final iteration;
annotation errors remain durable evidence failures rather than being converted to a soft score or a
hard verifier result.

## Public lifecycle

Use the registered presets through the unified entrypoint:

```bash
python3 scripts/bench.py check \
  --preset swe-bench-verified-sympy-16886-codex-smoke
python3 scripts/bench.py setup \
  --preset swe-bench-verified-sympy-16886-codex-smoke \
  --skip-provision
python3 scripts/bench.py plan \
  --preset swe-bench-verified-sympy-16886-codex-smoke
```

Use `swe-bench-verified-sympy-16886-goal-plus-pi-smoke` for the Goal Plus + Pi path. It freezes
`T=1800,K=1,C=1,R=1`, a 1500-second worker budget, and a 300-second Search closeout reserve.
Use `swe-bench-verified-sympy-16886-goal-plus-pi-luna-high-smoke` for the same topology with the
profile-frozen `bench-openai/gpt-5.6-luna` Responses provider and high reasoning.

For the Acceptance View mechanism ablation, run
`swe-bench-verified-sympy-16886-acceptance-view-off-smoke` and
`swe-bench-verified-sympy-16886-acceptance-view-on-smoke`. Both profiles freeze the same task,
provider, model, reasoning, ViewAgent, and `T/K/C/R`; only the Acceptance View policy differs. ON
sets both `GOAL_PLUS_ACCEPTANCE_VIEW_ENABLED=1` and
`GOAL_PLUS_ACCEPTANCE_VIEW_REQUIRED=1`, so a missing or underspecified rubric cannot silently
degrade into the OFF condition. The official SWE-bench `resolved` result remains the sole hard
score. Reports preserve the frozen rubric, per-iteration Global Evidence entries, ViewAgent token
usage, and the completion checks that prove the intended condition actually ran.

Run `launch` only after reviewing and confirming the resolved `T/K/C/R` block. A terminal campaign
is archived with `finish`, which consumes `campaign-summary.json` and exports `report.md` plus the
campaign-named workbook.

That `finish` archive is campaign-local. For adaptation readiness, review and sanitize the minimum
evidence into `evidence/runs/`, bind it to the exact method with registry `stage_evidence`, and
promote the method in the same change. Repository validation rejects a method pass without that
mapping.

The task image itself is never removed by this controller. The official evaluator is fixed to
`cache_level=instance`, `clean=false`, and `force_rebuild=false`. To preserve the stopped Agent
container as well, add `--retain-containers` to both `plan` and `launch`; the resolved spec, manifest,
status, and final report record the retained Agent container. The official harness still cleans its
separate evaluation container and preserves its logs. `finish` does not clean up the retained Agent
container.

## Mirrors

The controller does not rewrite Docker references or dataset revisions. A domestic PyPI or
Hugging Face endpoint may accelerate transfer when the official endpoint is unavailable, but the
profile SHA and exact image tag remain authoritative. Existing local assets do not trigger a pull.

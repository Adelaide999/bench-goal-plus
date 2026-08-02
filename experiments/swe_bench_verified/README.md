# SWE-bench Verified native lifecycle

This controller keeps the official SWE-bench harness as the final evaluator while exposing the
repository lifecycle through `python3 scripts/bench.py`.

## Initial scope

| Contract | Frozen value |
| --- | --- |
| Dataset | `SWE-bench/SWE-bench_Verified` at `91aa3ed51b709be6457e12d00300a6a596d4c6a3` |
| Instance | `sympy__sympy-16886` |
| Image | `swebench/sweb.eval.x86_64.sympy_1776_sympy-16886:latest` |
| Methods | `plain-codex`, `plain-pi` |
| Budget | `T=1800`, `K=1`, `C=1`, `R=1` |
| Metric | official `resolved`, maximize |
| Codex auth | `OPENAI_BASE_URL` + `OPENAI_API_KEY`, OpenAI-compatible Responses |

Goal Plus, detached execution, stop/resume, `K>1`, `C>1`, and automatic image provisioning are
not supported by this initial acceptance path.

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

Run `launch` only after reviewing and confirming the resolved `T/K/C/R` block. A terminal campaign
is archived with `finish`, which consumes `campaign-summary.json` and exports `report.md` plus the
campaign-named workbook.

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

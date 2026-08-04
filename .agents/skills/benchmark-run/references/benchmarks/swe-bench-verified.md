# SWE-bench Verified runner reference

## Selected contract

- Target: `swe-bench-verified`
- Runner: `swe-bench-native`
- Initial task: `sympy__sympy-16886`
- Raw metric: official `resolved` boolean, direction `maximize`
- Methods: `plain-codex`, `plain-pi`, `goal-plus-codex`, and `goal-plus-pi`
- Topology: Plain methods use one isolated outer trajectory. Goal Plus uses one outer main session
  with one bound internal worker on the selected Codex or Pi host. Initial acceptance restricts
  every method to `K=1,C=1,R=1`
- Final source JSON: `campaign-summary.json`

The official harness owns final scoring in a separate container. The runner has no host-only score,
provision, detach, stop, resume, or cross-cell concurrency.

## Presets

| Preset | Model | T/K/C/R | Auth |
| --- | --- | --- | --- |
| `swe-bench-verified-sympy-16886-codex-smoke` | `gpt-5.6-sol`, medium | `1800/1/1/1` | profile-frozen `OPENAI_BASE_URL` + `OPENAI_API_KEY`, Responses |
| `swe-bench-verified-sympy-16886-pi-smoke` | `zai/glm-5.2`, medium | `1800/1/1/1` | inherited `ZAI_API_KEY` |
| `swe-bench-verified-sympy-16886-goal-plus-pi-smoke` | `zai/glm-5.2`, medium | `1800/1/1/1` | inherited `ZAI_API_KEY` |
| `swe-bench-verified-sympy-16886-goal-plus-pi-luna-high-smoke` | `bench-openai/gpt-5.6-luna`, high | `1800/1/1/1` | profile-frozen `OPENAI_BASE_URL` + `OPENAI_API_KEY`, Responses |
| `swe-bench-verified-sympy-16886-acceptance-view-off-smoke` | `bench-openai/gpt-5.6-luna`, high | `1800/1/1/1` | Acceptance View disabled mechanism ablation |
| `swe-bench-verified-sympy-16886-acceptance-view-on-smoke` | `bench-openai/gpt-5.6-luna`, high | `1800/1/1/1` | Acceptance View enabled mechanism ablation |
| `swe-bench-verified-sympy-16886-goal-plus-codex-acceptance-off-smoke` | `gpt-5.6-luna`, high | `1800/1/1/1` | Goal Plus + Codex Responses, Acceptance View disabled |
| `swe-bench-verified-sympy-16886-goal-plus-codex-acceptance-on-smoke` | `gpt-5.6-luna`, high | `1800/1/1/1` | Goal Plus + Codex Responses, Acceptance View enabled |

The Pi credential value is never serialized. Docker receives only the selected environment variable
name. The complete dataset row is host-side evaluator input; the Agent receives only the public
issue allowlist.

The Luna profile materializes a campaign-local Pi `models.json` containing only the endpoint and
`$OPENAI_API_KEY` environment reference. A Linux loopback endpoint uses the same repository-owned
socket bridge as Plain Codex; doctor must pass host Responses, task-container Responses, and Pi's
exact `bench-openai/gpt-5.6-luna` model listing before launch.

Both Luna Acceptance View ablation profiles run the same independent Codex ViewAgent on every
persisted candidate iteration. OFF publishes only a candidate evidence description. ON additionally
requires MainAgent to freeze 3–8 benchmark-adaptive, task-specific soft criteria and publishes their
status, confidence, rationale, and supporting evidence in Global Evidence View. There is no soft
aggregate score: official `resolved` remains the sole hard result. A missing ON rubric, incomplete
ViewAgent task, criterion mismatch, or OFF assessment leakage makes Goal Plus evidence incomplete
and therefore the campaign `partial`, while preserving a valid official raw metric.

The Goal Plus + Codex pair uses the same Responses endpoint and key contract as Plain Codex and
does not mount OAuth. Its ON/OFF prompts, task, evaluator, model, reasoning, and T/K/C/R are
byte-identical; only the frozen Acceptance View boolean differs.

The archived Linux/amd64 `sympy__sympy-16886` smokes pass the complete `K=1,C=1`
official-harness contract for
[Plain Codex](../../../../../evidence/runs/2026-08-02-swe-bench-verified-plain-codex-sol/summary.json),
[Plain Pi](../../../../../evidence/runs/2026-08-02-swe-bench-verified-plain-pi-glm/summary.json),
and [Goal Plus + Pi](../../../../../evidence/runs/2026-08-03-swe-bench-verified-goal-plus-pi-luna/summary.json).
The two Plain development smokes preserve their dirty-at-prepare provenance and later acceptance
commit instead of rewriting it. `K>1`, other instances, and split-wide readiness remain separate
claims.

## Completion evidence

A cell is score-complete only when all of the following are present:

1. the Agent container was isolated before evaluation, either by confirmed removal or by confirmed
   stopped retention requested through `--retain-containers`;
2. a non-empty binary/full-index model patch was exported;
3. exactly one official evaluator attempt was recorded;
4. the official per-instance `report.json` contains a boolean `resolved` field;
5. raw `resolved` and `patch_successfully_applied` values are preserved.

An unresolved result is a valid completed score. Missing patch, missing report, unconfirmed
container isolation, or a second evaluator attempt is `partial` or `failed`, not a zero-filled
success.

For Goal Plus methods, score completion additionally requires exported durable state proving exactly
one terminal Goal Plus record and linked promoted Search run, a frozen spec with
`budget.max_parallel=K`, the method's bound `codex` or `pi-rpc` worker topology, the frozen
worker/closeout budgets, one candidate, one bound worker session, worker-origin verifier evidence,
the registered visible-test wrapper, and no active Pi pool job. When the profile enables the
ViewAgent, every candidate iteration must
have a completed Global Evidence description. Acceptance View ON additionally requires a frozen
3–8 criterion contract and an exactly matching per-criterion assessment; OFF requires the contract
and assessments to be absent. The controller exports `/testbed/.gp` before container disposal.
Missing Goal Plus evidence downgrades the cell to `partial` while preserving any complete official
raw score.

## Debug container retention

The exact task image is always retained: the controller invokes the official harness with
`cache_level=instance`, `clean=false`, and `force_rebuild=false`, and it never calls `docker rmi`.
Normal campaigns remove the Agent container after exporting the patch. For an inspectable Agent
filesystem, pass the same option to both plan and launch:

```bash
python3 scripts/bench.py plan \
  --preset swe-bench-verified-sympy-16886-codex-smoke \
  --campaign-id swe-debug-example \
  --retain-containers
python3 scripts/bench.py launch \
  --preset swe-bench-verified-sympy-16886-codex-smoke \
  --campaign-id swe-debug-example \
  --retain-containers
```

The controller stops rather than removes its Agent container, records its exact name/ID and cleanup
disposition in `campaign.json`, and then runs the official evaluator in a separate harness-owned
container. The current flag retains the Agent container only; the official harness still cleans its
evaluation container while preserving its report and logs. `status` and the final report expose the
retained Agent container. `finish` leaves it untouched; inspection or later explicit cleanup is a
user-controlled Docker operation. The temporary loopback API bridge closes when the Agent trajectory
ends, so retention preserves the filesystem and process state boundary, not a live provider route.

## Lifecycle

Run the profiled `check`, then `setup --skip-provision`, then `plan`. Before `launch`, show the
resolved confirmation block required by the benchmark-run Skill. Because execution is foreground
and non-resumable, run the method campaigns sequentially. At terminal state, use unified
`status` and `finish`; do not invoke the native controller as a second public CLI.

`finish` creates campaign-local final evidence and reports; it does not edit the source registry.
During adaptation acceptance, project the reviewed, secret-free minimum into `evidence/runs/`, map
it to the exact method through registry `stage_evidence`, and promote that method in the same
change. A `benchmark_methods` pass without method-specific evidence fails repository validation.

Domestic mirrors are transport fallbacks only. They may not change the dataset revision, official
checkout branch, image tag, image ID, or evaluator implementation.

## Environment failures and recovery

- If `prepare` cannot reach `huggingface.co`, first confirm the exact image is already local. Route
  `XDG_CACHE_HOME` and `HF_HOME` below the repository `.tmp/`, then use `HF_ENDPOINT` only as a
  transport fallback for the registered dataset revision. Once cached, set `HF_HUB_OFFLINE=1` and
  `HF_DATASETS_OFFLINE=1` for the campaign.
- A task image HEAD different from the dataset `base_commit` is not by itself a mismatch. Official
  images may add an empty synthetic commit. Full doctor must prove equal Git tree IDs before launch;
  never edit, retag, rebuild, or replace the image to make the SHAs look equal.
- A failed `prepare` has not started an Agent and has not called the evaluator. Keep any empty or
  partial path with the normal `_bak` preservation rule, fix the environment, generate a fresh plan,
  and use the new planned campaign ID.
- The shared Codex runtime and Pi installations are read-only host prerequisites. Mutable cache,
  campaign, evaluator, and temp paths must remain below the selected bench-goal-plus checkout.
- Goal Plus + Pi installs the repository lock into the disposable Agent container and uses only the
  repository-local `.tmp/swe-bench-verified/goal-plus-pip-cache` as a persistent writable cache.
  Goal Plus source, Node, Pi, the dependency lock, and controller/verifier assets are mounted
  read-only. `PIP_INDEX_URL` may select a domestic transport mirror, but it cannot change the lock,
  image, dataset revision, or official evaluator.
- Plain Codex does not use an OAuth auth file on this target. The profile freezes
  `auth_mode=openai-compatible`, `base_url_env=OPENAI_BASE_URL`,
  `api_key_env=OPENAI_API_KEY`, and `wire_api=responses`; doctor must prove the exact model through
  host `POST /responses`, the Linux loopback bridge when needed, and task-container
  `POST /responses`. Seeing a request to `chatgpt.com` is a blocking routing regression, not a
  custom-provider outage. Do not fall back to OAuth or substitute `SFORGE_AGENT_*` when both
  protocol configurations exist.
- Codex runtime extraction must fit the same bounded tmpfs in doctor and run. A pre-Agent
  `No space left on device` result has no model/evaluator call; finish that failed campaign, fix and
  test the tmpfs contract, then create a fresh planned campaign rather than retrying it in place.
  The runtime mount also needs explicit `exec` because the pinned binary runs from `/opt/codex`;
  retain `nosuid,nodev` and verify the exact mount through full doctor.

The full installation and mirror procedure is in the
[benchmark setup matrix](../../../benchmark-setup/references/benchmark-matrix.md#swe-bench-verified-on-a-shared-linux-host).

# SWE-bench Verified runner reference

## Selected contract

- Target: `swe-bench-verified`
- Runner: `swe-bench-native`
- Initial task: `sympy__sympy-16886`
- Raw metric: official `resolved` boolean, direction `maximize`
- Methods: `plain-codex` and `plain-pi`
- Topology: one isolated outer Agent trajectory, so only `K=1,C=1,R=1` is accepted
- Final source JSON: `campaign-summary.json`

The official harness owns final scoring in a separate container. The runner has no host-only score,
provision, detach, stop, resume, cross-cell concurrency, or Goal Plus capability.

## Presets

| Preset | Model | T/K/C/R | Auth |
| --- | --- | --- | --- |
| `swe-bench-verified-sympy-16886-codex-smoke` | `gpt-5.6-sol`, medium | `1800/1/1/1` | profile-frozen `OPENAI_BASE_URL` + `OPENAI_API_KEY`, Responses |
| `swe-bench-verified-sympy-16886-pi-smoke` | `zai/glm-5.2`, medium | `1800/1/1/1` | inherited `ZAI_API_KEY` |

The Pi credential value is never serialized. Docker receives only the selected environment variable
name. The complete dataset row is host-side evaluator input; the Agent receives only the public
issue allowlist.

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
and non-resumable, run the two method campaigns sequentially. At terminal state, use unified
`status` and `finish`; do not invoke the native controller as a second public CLI.

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

# ZSoft Detect native SWE-agent

Use runner `zsoft-detect-native` only for target
`zsoft-detect-swe-agent` and method `zsoft-swe-agent`. This is the benchmark's
own `runners/launch.py swe-agent` lifecycle, not SWE-bench Agent and not the
common Codex/Goal Plus runner.

## Fixed native contract

- host: Linux with Bubblewrap and the required user-namespace flags;
- tool: clean SWE-agent checkout at
  `6aff2155dd6fb2a8d19069f5c344f85a54f6c2fa` (SWE-agent 1.0.1), with
  SWE-ReX 1.4.0 and LiteLLM 1.93.0 in its `.venv`;
- auth: host-only `OPENAI_COMPAT_BASE_URL`, `OPENAI_COMPAT_API_KEY`, and
  optional JSON-object `OPENAI_COMPAT_HEADERS_JSON`;
- topology: one outer SWE-agent trajectory per cell, so `K=1`; initial
  acceptance also fixes `C=1`; `R` creates independent cells;
- output: `submission/*.json`, upstream `run-metrics.json`, exact metered
  provider usage, and official scorer F1/precision/recall/TP/FP/FN;
- lifecycle: foreground and non-resumable; retry uses a new campaign ID.

The upstream launcher does not expose reasoning effort. Preserve the profile's
requested label for provenance, but mark the result ineligible for a
reasoning-matched comparison; do not claim the label was applied to SWE-agent.

OrbStack may supply Docker for other targets, but does not replace this
native Linux+bwrap host. Do not run the launcher in an invented Docker wrapper
or substitute the common adapter's agent execution.

Before any provisioning:

```bash
python3 scripts/bench.py check \
  --benchmark zsoft-detect-swe-agent \
  --profile civetweb-swe-agent-smoke
```

Then use `setup`, `plan`, `launch`, `status`, and `finish` through
`scripts/bench.py`. A nonzero launcher, incomplete provider usage, missing
`run-metrics.json`, or failed scorer leaves the cell `partial`; retain any raw
score and artifacts.

# ZSoft Detect native SWE-agent

This controller exposes the benchmark-owned `runners/launch.py swe-agent`
path as a dedicated bench-goal-plus target. It does not replace or emulate
the upstream lifecycle: ZSoft still owns source snapshotting, the Bubblewrap
sandbox, prompt/config, metered OpenAI-compatible proxy, submission layout,
token ledger, and deterministic scorer.

The public method is `zsoft-swe-agent`, supported only by target
`zsoft-detect-swe-agent`. The existing `zsoft-detect` target remains the common
Codex/Goal Plus comparison path.

Execution requires a Linux host with Bubblewrap. OrbStack's Docker daemon on
macOS does not satisfy the native host contract. The default ignored asset
locations are `.bench-env/zsoft-detect-swe-agent/SWE-agent` and
`.bench-env/zsoft-detect-swe-agent/sources/<project>-<commit>`; an explicitly
managed checkout may be selected with `BENCH_GOAL_PLUS_SWE_AGENT_ROOT`.

Credentials stay in the host environment:

- `OPENAI_COMPAT_BASE_URL`
- `OPENAI_COMPAT_API_KEY`
- optional `OPENAI_COMPAT_HEADERS_JSON`

They are not copied into commands, manifests, prompts, or reports.

Use only the unified lifecycle:

```bash
python3 scripts/bench.py check \
  --benchmark zsoft-detect-swe-agent --profile civetweb-swe-agent-smoke
python3 scripts/bench.py setup \
  --benchmark zsoft-detect-swe-agent --profile civetweb-swe-agent-smoke
python3 scripts/bench.py plan \
  --preset zsoft-detect-civetweb-swe-agent-smoke
python3 scripts/bench.py launch \
  --preset zsoft-detect-civetweb-swe-agent-smoke \
  --campaign-id <planned-id> --skip-bootstrap --skip-provision
python3 scripts/bench.py status \
  --benchmark zsoft-detect-swe-agent --campaign <planned-id>
python3 scripts/bench.py finish \
  --benchmark zsoft-detect-swe-agent --campaign <planned-id>
```

A cell is complete only when the native launcher exits successfully,
`run-metrics.json` says `complete`, provider usage is exact and complete, and
the official scorer returns raw F1/precision/recall/TP/FP/FN. Otherwise the
score and artifacts are retained but the cell remains `partial`.

The upstream launcher does not expose an explicit reasoning-effort knob. The
profile records the requested label, but native SWE-agent results remain
ineligible for a reasoning-matched comparison until the upstream protocol adds
and validates that control.

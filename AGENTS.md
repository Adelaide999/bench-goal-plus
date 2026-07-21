# bench-goal-plus contributor rules

This repository is the control plane for Goal Plus benchmark integrations.

- Keep benchmark upstreams in separate forks. Do not vendor their source or datasets here.
- Pin every upstream/fork commit in `benchmarks/registry.json`.
- Put cross-benchmark orchestration and adapters here; patch a benchmark fork only when the change is intrinsically benchmark-specific.
- Never persist API keys, auth files, cookies, provider headers, or secret-bearing command lines.
- A status can become `pass` only when a reproducible command and evidence file exist. Repository support or an unexecuted code path is at most `partial`.
- Keep three claims separate: official verifier works, plain Codex works, and Goal Plus + Codex works.
- Preserve raw benchmark metrics and direction. Any normalized aggregate must be an additional field, not a replacement.
- Match evaluator calls first; record model calls, tokens, cost, wall time, host, commit, and environment as secondary budgets.
- Run `python3 scripts/status.py --check` and `python3 -m unittest discover -s tests -v` before committing.


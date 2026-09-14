# Fixed Circle Packing With Unified Goal Plus

The public OpenEvolve Circle Packing lifecycle passed with ordinary fixed
candidates after removing Bench's retired optional Search Scheduler integration.
This validates the Pi portable Circle path only. It does not claim Adaptive,
quality scoring, Docker benchmark, or Codex real-model acceptance.

## Configuration

- Goal Plus commit: `5dd1fdeee3f610c86774459c0a3aa7af115c20b8`.
- Managed build:
  `9a92d5cbbc1ea204918ae4a2773fc8bd018c338db987e07ea9b9d52f6d43cae6`.
- OpenEvolve commit: `411fb59c886c18704caaffb611e17cf9e7d824d2`.
- Main and candidate: Pi `0.84.2`, `bench-openai/gpt-5.6-sol`, reasoning `low`.
- Python: `3.12.13`; run-local managed installation, no global configuration edits.
- T/K/C/R: `600/1/1/1`; planned closeout reserve 60 seconds, kill grace 30 seconds.
- Frozen mode: `parallel_loops`, ranking keys `[hard_score]`, tolerance `[0.0]`.
- Allocation is null; no LLM Verifier tasks, records, or Allocation Decisions.
- Existing Evidence annotation remains configured; it does not rank candidates.
- Independent Goal final check is disabled; promotion has its separate verifier.

The public sequence was `catalog`, `setup`, `plan`, `launch`, `status`, `finish`.
Setup used the same benchmark, method, model and provider arguments shown below,
with `--skip-bootstrap --skip-provision`. The external source was selected with
`BENCH_GOAL_PLUS_SOURCE_DIR` pointing to the clean Goal Plus checkout and
`BENCH_GOAL_PLUS_EXPECTED_REF` set to the full commit above.

```bash
python3 scripts/bench.py launch \
  --benchmark openevolve-cpu-portable \
  --task-id circle_packing_with_artifacts --method goal-plus-pi \
  --model gpt-5.6-sol --reasoning-effort low --wall-time-seconds 600 \
  --live-search-concurrency 1 --cell-concurrency 1 --seed 1 \
  --pi-provider-id bench-openai --pi-api openai-responses \
  --pi-api-key-env OPENAI_API_KEY --pi-api-base-env OPENAI_BASE_URL \
  --campaign-id circle-fixed-unified-20260914-r2 \
  --skip-bootstrap --skip-provision
```

## Accepted Run

Campaign: `runs/openevolve-campaigns/circle-fixed-unified-20260914-r2`.
The cell below it is `circle_packing_with_artifacts/goal-plus-pi`.

| Evidence | Result |
| --- | --- |
| Public status | `succeeded`, terminal; Agent phase `reported` |
| Goal | `gp_0001`, complete, Search result recorded |
| Search run | `run_b04c239a0c71a98fa70016f9f196f81a` |
| Session | `agent_b04c239a0c71a98fa70016f9f196f81a_001` |
| Execution | 1 candidate, 1 bound native session, 1 actual invocation |
| Evidence | c001 iteration 1, process passed, exact worker artifact |
| Selected commit | `2db6e1c8a420ef1ffa6c1dd83b2adb2b093691ad` |
| Applied source commit | `069b39db0a14dfad5bda9d25922161520965a294` |
| Final validity | true; 26 circles, zero boundary violations and overlaps |
| Seed combined score | `0.36423689449571406` |
| Final combined score | `0.9931007974078798`, maximize |
| Final sum of radii | `2.616820601169763` |
| Outer runtime | `573.7529667462222` seconds; no timeout or hard kill |
| Evaluator calls | 10 total: 1 setup, 8 further public, 1 final |
| Scope | `scope_3b8830dcf33821ab7630`, closed, active count 0, no errors |
| Controller closeout | completed; reused applied publication, no new scoring |

Final candidate SHA-256:
`29db0b49434915e837554366a913e94096b75bdd6fac7b045fc7cdd96ff6247a`.
The selected Git artifact, applied source file and exported candidate match this
hash. Final evaluation equals independent promotion verification and the selected
hard score. Frozen verifier hashes are unchanged; the source Git tree is clean.

Campaign artifacts include `campaign-summary.json`, `report.md` and
`circle-fixed-unified-20260914-r2.xlsx` with Summary and Results sheets.
The cell contains `experiment.json`, `goal-plus-runtime.json`, `final-eval.json`,
`final-candidate.py`, native sessions and `.gp` under `workspace/`.
The linked run contains final `report.md` and `report.html`.

Local diagnostic logs are `.tmp/circle-fixed-setup.log`,
`.tmp/circle-fixed-r2-{plan,launch,finish}.log` (plan uses `.json`),
`.tmp/circle-fixed-r2-status.json` and
`.tmp/circle-fixed-r2-verification.json`. Main instruction audit used the exact
installed build and observed the selected provider/model without provider errors.

## Preserved First Attempt

`circle-fixed-unified-20260914` remains archived as incomplete. Its Goal, two
same-session candidate calls, independent promotion, apply and final evaluation
succeeded: sum of radii `2.630226393763405`, combined score `0.998188384729945`.
Bench closeout then failed on the deleted `SearchTools.search_report` method.
The fix uses current `goal_plus_search_*` methods in Common/OpenEvolve and SWE
closeout. Tests constrain mocks to the actual SearchTools interface. The accepted
campaign above was a fresh full rerun, not a status rewrite of this attempt.

## Automated Checks

- Locked unittest discovery: 518 tests, OK, 1 skipped for missing Bubblewrap.
- The installed MCP SDK round-trip was enabled and passed.
- Locked status: 15 registry items and 8 datasets validated.
- `git diff --check`, undefined-name checks, affected relative links passed.
- Markdown: no issues on changed lines; 49 existing issues elsewhere in the five
  affected documents remain. Full Markdown lint is not clean.
- Log: `.tmp/fixed-search-unit-final.log`.

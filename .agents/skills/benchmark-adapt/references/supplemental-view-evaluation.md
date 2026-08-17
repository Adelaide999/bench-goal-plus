# Open supplemental ViewAgent evaluation

Use this contract when a benchmark enables Goal Plus post-settlement supplemental evaluation.
It is a cross-benchmark evidence mechanism, not a benchmark-specific rubric.

## Invariants

- FrozenSpec contains only hard metrics, verifiers, edit scope, budgets, and promotion contracts.
  Never add `acceptance_view`, soft criteria, predefined dimensions, or a soft aggregate score.
- The official/native benchmark metric remains the sole hard result. Supplemental output cannot
  change verifier PASS/FAIL, candidate settlement, candidate-local baseline, selection, promotion,
  or the preserved raw metric.
- ViewAgent runs after a verifier-backed candidate commit settles. Each invocation derives 1-8
  atomic supported/unresolved observations from the current Evidence; it does not inherit prior
  labels or observations.
- ViewAgent does not receive or compare peer candidates. It must not emit summary, confidence,
  winner, recommendation, or hidden-result inference. Dynamic comparison is a separate worker-led,
  deterministic read operation over already-published observations.
- Candidate workers receive only the resulting Global Evidence view. Raw task context is resolved
  only for ViewAgent; reports retain its provenance and SHA-256, not another plaintext copy.

## Adapter mapping

Every benchmark adapter maps its visible data into four roles:

| Role | Required content | Forbidden content |
| --- | --- | --- |
| visible task context | Exact user request or benchmark-visible task statement, with immutable provenance | hidden tests, judge data, answer patches, model-written soft criteria |
| candidate artifact | Current cumulative artifact or a deterministic representation of it | chain of thought, uncommitted guesses, unrelated workspace files |
| hard Evidence | Public verifier result, raw metric, disposition, and relevant observed diagnostics | fabricated pass claims, normalized replacement for native metrics |

The mapping depends on artifact shape, not benchmark name:

- Git code repair: public issue, cumulative Git diff, and visible test result.
- Program or algorithm optimization: public objective, current program/config, native public metric,
  and public diagnostics.
- Structured document or design task: visible request, rendered or structured artifact snapshot,
  and deterministic checks.
- Service/browser/native harness: visible task state, exported candidate action/artifact trace, native
  public checks. Keep hidden judge state inside the native harness.

If the runner cannot provide a trustworthy deterministic candidate representation, keep
supplemental evaluation disabled and report the capability as `partial`; do not substitute a generic
checklist. Claim dynamic peer comparison only after a `K>=2` smoke persists an independent
`global_evidence_comparisons` receipt whose selected peer observations resolve to immutable Views.

## Durable evidence gate

For every verifier-settled worker iteration, persist and validate:

1. completed objective description;
2. task-context source, immutable reference, and SHA-256;
3. feature flag matching the frozen campaign profile;
4. one to eight observations when enabled, each with state, open label, text, and one to four
   structured visible-Evidence references, or no supplemental output when disabled;
5. absence of summary, confidence, comparison basis, peer comparison, legacy soft rubrics, and
   Acceptance View output;
6. backward read compatibility for v1 dimensions/limitations without rewriting the original file;
7. for each claimed dynamic comparison, a separate receipt containing 2-8 unique exact observation
   references, at most two per candidate, and no score or winner field.

Keep annotation coverage separate from official score completeness. A missing/malformed ViewAgent
output can make mechanism evidence `partial`, but it cannot replace or zero-fill a valid official raw
metric. Record ViewAgent host, model, reasoning, token/cost coverage, and actual wall time. For a
quality-effect claim, additionally record whether a worker read a completed supplemental view before
its next verifier attempt; generation during closeout proves archive coverage, not search influence.

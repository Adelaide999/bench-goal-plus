# HeuriGym adapter

The first supported HeuriGym task is `operator_scheduling_demo`. It is CPU-only,
uses five public demo instances, and exposes exactly one editable artifact:
`solver.py`.

The adapter:

- downloads only the five pinned public cases from
  `heurigen/heurigen-data@c11ab2d` when they are absent;
- verifies every case hash before materialization;
- copies the cases into an isolated Git workspace under ignored `runs/`;
- invokes HeuriGym's own `operator_scheduling/program/verifier.py` and
  `evaluator.py` through a controller-owned wrapper;
- records every public/final evaluator call outside the editable surface;
- reports aggregate `total_cost`, where lower is better.

The seed is a valid sequential topological scheduler with aggregate cost 138.
Only `solver.py` may change. Goal Plus verifier scratch data uses
`GOAL_PLUS_VERIFIER_TMPDIR`, so verifier execution leaves the candidate Git
workspace unchanged.

Use the comparison runner in
[`experiments/heurigym_compare`](../../experiments/heurigym_compare/README.md)
rather than calling this module directly for a model run.

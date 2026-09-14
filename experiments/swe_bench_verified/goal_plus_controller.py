#!/usr/bin/env python3
"""Controller-owned Goal Plus closeout inside a SWE-bench Agent container."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected a JSON object: {path}")
    return payload


def _close_candidate_sessions(root: Path, timeout_seconds: int) -> list[dict[str, Any]]:
    from goal_plus.host_scope import close_run_candidates, execution_scope_for_run

    summaries = []
    for path in sorted((root / "runs").glob("run_*/run.json")):
        run_id = path.parent.name
        scope = execution_scope_for_run(root_dir=root, run_id=run_id)
        if scope is None:
            raise RuntimeError(f"Search run {run_id} has no native execution scope")
        if scope.get("state") == "closed":
            cleanup = scope.get("cleanup") or {}
            if cleanup.get("active_count") != 0 or cleanup.get("errors") != []:
                raise RuntimeError(f"Search run {run_id} lacks successful scope cleanup")
            summaries.append({"run_id": run_id, "active_count": 0, "scope_id": scope["scope_id"]})
        else:
            summaries.append(close_run_candidates(
                root_dir=root, scope_id=scope["scope_id"], run_id=run_id,
                timeout_seconds=timeout_seconds,
            ))
    return summaries


def _existing_selection(
    run_path: Path,
) -> tuple[dict[str, Any], str, dict[str, Any]] | None:
    run = _read_json(run_path)
    if run.get("state") != "ready_to_promote":
        return None
    candidate_id = run.get("selected_candidate_id")
    if not isinstance(candidate_id, str) or not candidate_id:
        raise RuntimeError("ready-to-promote Search run has no selected candidate")
    return (
        run,
        candidate_id,
        {
            "selected_candidate_id": candidate_id,
            "selected_score": run.get("selected_score"),
            "selected_iteration": run.get("selected_iteration"),
            "reused_existing_selection": True,
        },
    )


def _existing_promotion(
    run_path: Path,
) -> tuple[dict[str, Any], str, dict[str, Any], dict[str, str]] | None:
    run = _read_json(run_path)
    if run.get("state") != "promoted":
        return None
    candidate_id = run.get("selected_candidate_id")
    if not isinstance(candidate_id, str) or not candidate_id:
        raise RuntimeError("promoted Search run has no selected candidate")
    patch = run_path.parent / "promotion" / f"{candidate_id}.patch"
    if not patch.is_file():
        raise RuntimeError("promoted Search run has no promotion artifact")
    return (
        run,
        candidate_id,
        {
            "selected_candidate_id": candidate_id,
            "selected_score": run.get("selected_score"),
            "selected_iteration": run.get("selected_iteration"),
            "reused_existing_promotion": True,
        },
        {"artifact_path": str(patch)},
    )


def closeout(root: Path, source: Path, *, session_timeout_seconds: int) -> dict[str, Any]:
    """Drain host workers and idempotently finish every linked Search run."""
    from goal_plus.evidence_annotator import drain_evidence_annotations
    from goal_plus.goal_plus import FileGoalPlusRuntime
    from goal_plus.runtime import FileSearchRuntime
    from goal_plus.tools import SearchTools

    started = time.monotonic()
    root = root.resolve()
    source = source.resolve()
    result: dict[str, Any] = {
        "completed": False,
        "root": str(root),
        "source": str(source),
        "candidate_session_cleanup": [],
        "runs": [],
    }
    try:
        result["candidate_session_cleanup"] = _close_candidate_sessions(root, session_timeout_seconds)
        goal_runtime = FileGoalPlusRuntime(root)
        search_runtime = FileSearchRuntime(root)
        tools = SearchTools(search_runtime)
        goals_by_run: dict[str, list[str]] = {}
        for goal_path in sorted((root / "goal-plus").glob("gp_*/goal.json")):
            goal = goal_runtime.status(goal_path.parent.name)
            if goal.linked_search is not None and goal.linked_search.run_id:
                goals_by_run.setdefault(goal.linked_search.run_id, []).append(
                    goal.goal_plus_id
                )

        for run_id, goal_ids in goals_by_run.items():
            run_path = root / "runs" / run_id / "run.json"
            run = _read_json(run_path)
            configured_source = Path(str(run.get("source_path") or "")).resolve()
            if configured_source != source:
                raise RuntimeError(
                    f"Search run {run_id} source_path escaped /testbed: "
                    f"{configured_source}"
                )
            candidates = sorted(run_path.parent.glob("candidates/*/candidate.json"))
            if not candidates:
                continue

            verified_in_closeout: list[str] = []
            annotated_in_closeout = 0
            existing_promotion = _existing_promotion(run_path)
            existing_selection = (
                None
                if existing_promotion is not None
                else _existing_selection(run_path)
            )
            if existing_promotion is None and existing_selection is None:
                for candidate_path in candidates:
                    candidate = _read_json(candidate_path)
                    if not candidate.get("iterations"):
                        tools.goal_plus_search_run_verifier(
                            run_id,
                            str(candidate["candidate_id"]),
                            hypothesis="controller post-budget final verification",
                        )
                        verified_in_closeout.append(str(candidate["candidate_id"]))

            annotated_in_closeout = drain_evidence_annotations(
                root,
                run_id,
                wait_for_retries=True,
            )
            if existing_promotion is not None:
                run, candidate_id, selection, promotion = existing_promotion
            else:
                if existing_selection is None:
                    selection = tools.goal_plus_search_select(run_id)
                    candidate_id = str(selection["selected_candidate_id"])
                    run = _read_json(run_path)
                else:
                    run, candidate_id, selection = existing_selection
                promotion = tools.goal_plus_search_promote(run_id, candidate_id)

            patch = Path(str(promotion["artifact_path"])).resolve()
            expected_promotion_root = (run_path.parent / "promotion").resolve()
            if patch.parent != expected_promotion_root:
                raise RuntimeError(
                    f"Search run {run_id} promotion artifact escaped its run: {patch}"
                )
            publication = search_runtime.promotion_record(run_id)
            if publication.state == "applied":
                patch_status = "already_applied"
            else:
                applied = tools.goal_plus_search_apply_promotion(run_id)
                if applied["state"] != "applied":
                    raise RuntimeError("Goal Plus publication has not been applied")
                patch_status = "applied"

            for goal_plus_id in goal_ids:
                goal = goal_runtime.status(goal_plus_id)
                linked = goal.linked_search
                if linked is None or linked.selected_candidate_id is None:
                    goal_runtime.record_search_result(
                        goal_plus_id,
                        run_id=run_id,
                        selected_candidate_id=candidate_id,
                        promotion_artifact_path=str(patch),
                        summary="SWE-bench controller finalized the fixed-budget Search run.",
                    )
                if goal_runtime.status(goal_plus_id).status != "complete":
                    goal_runtime.set_status(
                        goal_plus_id,
                        status="complete",
                        reason="fixed wall-clock search budget ended and controller closeout passed",
                        evidence=[
                            {
                                "type": "controller_closeout",
                                "run_id": run_id,
                                "selected_candidate_id": candidate_id,
                                "selected_score": selection.get("selected_score"),
                            }
                        ],
                    )
            report = tools.goal_plus_search_report(run_id)
            result["runs"].append(
                {
                    "run_id": run_id,
                    "goal_plus_ids": goal_ids,
                    "candidate_count": len(candidates),
                    "verified_in_closeout": verified_in_closeout,
                    "annotated_in_closeout": annotated_in_closeout,
                    "selection": selection,
                    "promotion": promotion,
                    "source_patch_status": patch_status,
                    "report": report,
                }
            )

        if not result["runs"]:
            raise RuntimeError("no linked Search run with materialized candidates exists")
        result["completed"] = True
    except Exception as error:
        result["error"] = f"{type(error).__name__}: {error}"
    result["duration_seconds"] = time.monotonic() - started
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("/testbed/.gp"))
    parser.add_argument("--source", type=Path, default=Path("/testbed"))
    parser.add_argument("--session-timeout-seconds", type=int, default=60)
    args = parser.parse_args(argv)
    payload = closeout(
        args.root,
        args.source,
        session_timeout_seconds=args.session_timeout_seconds,
    )
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    return 0 if payload["completed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

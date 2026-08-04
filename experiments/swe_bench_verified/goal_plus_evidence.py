"""Normalize persisted Goal Plus + Pi state for SWE-bench completion gates."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


ACTIVE_POOL_STATES = {"starting", "running"}
VISIBLE_VERIFIER_SUFFIX = ".goal-plus-verifiers/visible_test_verifier.py"
VISIBLE_VERIFIER_PATH = (
    Path(__file__).resolve().parent / "verifiers" / "visible_test_verifier.py"
)


def expected_visible_verifier_sha256() -> str:
    return hashlib.sha256(VISIBLE_VERIFIER_PATH.read_bytes()).hexdigest()


def _read_object(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _linked_run_id(goal: dict[str, Any]) -> str | None:
    linked = goal.get("linked_search") or {}
    if isinstance(linked, dict) and isinstance(linked.get("run_id"), str):
        return str(linked["run_id"])
    tasks = goal.get("search_tasks")
    if isinstance(tasks, list):
        for task in reversed(tasks):
            if isinstance(task, dict) and isinstance(task.get("run_id"), str):
                return str(task["run_id"])
    current = goal.get("current_search_run_id")
    return str(current) if isinstance(current, str) and current else None


def _check(expected: Any, actual: Any, passed: bool) -> dict[str, Any]:
    return {"expected": expected, "actual": actual, "passed": bool(passed)}


def record_completion_check(
    state: dict[str, Any],
    name: str,
    *,
    expected: Any,
    actual: Any,
    passed: bool,
) -> None:
    completion = state.setdefault("completion", {})
    checks = completion.setdefault("checks", {})
    checks[name] = _check(expected, actual, passed)
    failed = [key for key, check in checks.items() if not check.get("passed")]
    completion["passed"] = not failed
    completion["reason"] = (
        None
        if not failed
        else "Goal Plus completion evidence failed: " + ", ".join(failed)
    )


def _usage_from_sessions(sessions: list[dict[str, Any]]) -> dict[str, Any]:
    totals: dict[str, int | float] = {}
    covered = 0
    for session in sessions:
        handle = session.get("host_handle") or {}
        metadata = handle.get("metadata") if isinstance(handle, dict) else {}
        metrics = metadata.get("pi_metrics") if isinstance(metadata, dict) else {}
        usage = metrics.get("usage_total") if isinstance(metrics, dict) else {}
        if not isinstance(usage, dict):
            continue
        covered += 1
        for name, value in usage.items():
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                totals[name] = totals.get(name, 0) + value
    return {
        **dict(sorted(totals.items())),
        "sessions_covered": covered,
        "coverage": "persisted_pi_worker_usage" if covered else "unavailable",
    }


def _evidence_annotations(run_dir: Path, expected_iterations: int) -> dict[str, Any]:
    entries: list[dict[str, Any]] = []
    states: dict[str, int] = {}
    usage: dict[str, int | float] = {}
    for path in sorted(
        run_dir.glob("candidates/*/evidence-annotations/iteration-*.json")
    ):
        task = _read_object(path)
        state = str(task.get("state") or "unknown")
        states[state] = states.get(state, 0) + 1
        task_usage = (
            task.get("usage") if isinstance(task.get("usage"), dict) else {}
        )
        for name, value in task_usage.items():
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                usage[name] = usage.get(name, 0) + value
        view = task.get("view") if isinstance(task.get("view"), dict) else None
        profile = task.get("profile") if isinstance(task.get("profile"), dict) else {}
        entries.append(
            {
                "candidate_id": task.get("candidate_id"),
                "iteration": task.get("iteration"),
                "state": state,
                "annotator_host": profile.get("host"),
                "view": view,
                "last_error": task.get("last_error"),
            }
        )
    completed_views = [
        item
        for item in entries
        if item["state"] == "completed"
        and isinstance(item.get("view"), dict)
        and bool(item["view"].get("description"))
    ]
    return {
        "expected_iterations": expected_iterations,
        "task_count": len(entries),
        "states": dict(sorted(states.items())),
        "entries": entries,
        "usage": {
            **dict(sorted(usage.items())),
            "tasks": len(entries),
            "coverage": "persisted Codex Evidence annotator usage",
        },
        "all_completed": bool(
            expected_iterations > 0
            and len(entries) == expected_iterations
            and len(completed_views) == expected_iterations
        ),
    }


def _visible_verifier_contract(
    verifiers: Any,
    *,
    expected_role: str,
    expected_timeout_seconds: int,
) -> dict[str, Any]:
    records = verifiers if isinstance(verifiers, list) else []
    normalized = []
    for verifier in records:
        if not isinstance(verifier, dict):
            continue
        command = verifier.get("command")
        arguments = [str(item) for item in command] if isinstance(command, list) else []
        wrapper_present = any(
            argument.endswith(VISIBLE_VERIFIER_SUFFIX) for argument in arguments
        )
        timeout_value = None
        if "--timeout-seconds" in arguments:
            index = arguments.index("--timeout-seconds")
            if index + 1 < len(arguments):
                try:
                    timeout_value = int(arguments[index + 1])
                except ValueError:
                    timeout_value = None
        normalized.append(
            {
                "name": verifier.get("name"),
                "role": verifier.get("role"),
                "wrapper_present": wrapper_present,
                "wrapper_timeout_seconds": timeout_value,
                "command": arguments,
            }
        )
    passed = any(
        item["role"] == expected_role
        and item["wrapper_present"]
        and item["wrapper_timeout_seconds"] == expected_timeout_seconds
        for item in normalized
    )
    return {"passed": passed, "verifiers": normalized}


def _visible_verifier_integrity(frozen: dict[str, Any]) -> dict[str, Any]:
    verifier_hashes = (
        frozen.get("verifier_hashes")
        if isinstance(frozen.get("verifier_hashes"), dict)
        else {}
    )
    matching = {
        str(path): str(digest)
        for path, digest in verifier_hashes.items()
        if str(path).endswith(VISIBLE_VERIFIER_SUFFIX)
    }
    expected = expected_visible_verifier_sha256()
    return {
        "expected_sha256": expected,
        "frozen_hashes": matching,
        "passed": len(matching) == 1 and next(iter(matching.values())) == expected,
    }


def _promotion_visible_test(
    candidate_records: list[dict[str, Any]], selected_candidate_id: Any
) -> dict[str, Any]:
    candidate = next(
        (
            item
            for item in candidate_records
            if item.get("candidate_id") == selected_candidate_id
        ),
        {},
    )
    report = (
        candidate.get("promotion_report")
        if isinstance(candidate.get("promotion_report"), dict)
        else {}
    )
    visible_scores: list[float] = []
    for result in report.get("verifier_results") or []:
        if not isinstance(result, dict):
            continue
        metrics = (
            result.get("metrics")
            if isinstance(result.get("metrics"), dict)
            else {}
        )
        score = metrics.get("visible_test_score")
        if isinstance(score, (int, float)) and not isinstance(score, bool):
            visible_scores.append(float(score))
    passed = report.get("promotion_passed") is True and visible_scores == [1.0]
    return {
        "promotion_passed": report.get("promotion_passed"),
        "aggregate_score": report.get("aggregate_score"),
        "visible_test_scores": visible_scores,
        "passed": passed,
    }


def collect_goal_plus_state(
    root: Path,
    *,
    expected_k: int,
    expected_worker_runtime_seconds: int,
    expected_closeout_reserve_seconds: int,
    expected_visible_verifier_timeout_seconds: int,
    expected_acceptance_view_enabled: bool = False,
    expected_evidence_annotator_enabled: bool = False,
    expected_worker_host: str = "pi-rpc",
) -> dict[str, Any]:
    goal_records = []
    for path in sorted((root / "goal-plus").glob("gp_*/goal.json")):
        payload = _read_object(path)
        goal_records.append(
            {
                "goal_plus_id": payload.get("goal_plus_id"),
                "status": payload.get("status"),
                "phase": payload.get("phase"),
                "linked_run_id": _linked_run_id(payload),
            }
        )

    complete_goals = [item for item in goal_records if item.get("status") == "complete"]
    linked_run_ids = {
        str(item["linked_run_id"])
        for item in complete_goals
        if isinstance(item.get("linked_run_id"), str) and item.get("linked_run_id")
    }
    runs: list[dict[str, Any]] = []
    all_bound_sessions: list[dict[str, Any]] = []
    for path in sorted((root / "runs").glob("run_*/run.json")):
        payload = _read_object(path)
        run_id = str(payload.get("run_id") or path.parent.name)
        if run_id not in linked_run_ids:
            continue
        frozen_spec_id = payload.get("frozen_spec_id")
        frozen = (
            _read_object(root / "specs" / str(frozen_spec_id) / "frozen_spec.json")
            if isinstance(frozen_spec_id, str)
            else {}
        )
        spec = frozen.get("spec") if isinstance(frozen.get("spec"), dict) else {}
        strategy = spec.get("strategy") if isinstance(spec.get("strategy"), dict) else {}
        budget = spec.get("budget") if isinstance(spec.get("budget"), dict) else {}
        worker_budget = (
            strategy.get("worker_budget")
            if isinstance(strategy.get("worker_budget"), dict)
            else {}
        )
        strategy_config = (
            strategy.get("config") if isinstance(strategy.get("config"), dict) else {}
        )
        process_verifiers = _visible_verifier_contract(
            spec.get("process_verifiers"),
            expected_role="ranking_signal",
            expected_timeout_seconds=expected_visible_verifier_timeout_seconds,
        )
        promotion_verifiers = _visible_verifier_contract(
            spec.get("promotion_verifiers"),
            expected_role="promotion_gate",
            expected_timeout_seconds=expected_visible_verifier_timeout_seconds,
        )
        candidates = sorted(path.parent.glob("candidates/*/candidate.json"))
        candidate_records = [_read_object(candidate) for candidate in candidates]
        expected_annotation_iterations = sum(
            len(candidate.get("iterations") or [])
            for candidate in candidate_records
            if isinstance(candidate.get("iterations"), list)
        )
        acceptance_contract = (
            spec.get("acceptance_view")
            if isinstance(spec.get("acceptance_view"), dict)
            else None
        )
        evidence_annotator_spec = (
            strategy.get("evidence_annotator")
            if isinstance(strategy.get("evidence_annotator"), dict)
            else None
        )
        annotations = _evidence_annotations(
            path.parent, expected_annotation_iterations
        )
        sessions = [
            _read_object(session_path)
            for session_path in sorted(path.parent.glob("agent_sessions/agent_*.json"))
        ]
        bound_sessions: list[dict[str, Any]] = []
        bound_counts: dict[str, int] = {}
        verifier_candidate_ids: set[str] = set()
        for session in sessions:
            candidate_id = session.get("candidate_id")
            handle = session.get("host_handle") or {}
            bound_id = (
                handle.get("external_id") or handle.get("task_name")
                if isinstance(handle, dict)
                else None
            )
            if (
                session.get("host") == expected_worker_host
                and isinstance(candidate_id, str)
                and candidate_id
                and isinstance(bound_id, str)
                and bound_id
            ):
                bound_sessions.append(session)
                bound_counts[candidate_id] = bound_counts.get(candidate_id, 0) + 1
                counters = session.get("counters") or {}
                if isinstance(counters, dict) and int(counters.get("verifier_runs") or 0) > 0:
                    verifier_candidate_ids.add(candidate_id)
        all_bound_sessions.extend(bound_sessions)

        selected_candidate_id = payload.get("selected_candidate_id")
        verifier_integrity = _visible_verifier_integrity(frozen)
        promotion_visible_test = _promotion_visible_test(
            candidate_records, selected_candidate_id
        )
        promotion = (
            path.parent / "promotion" / f"{selected_candidate_id}.patch"
            if isinstance(selected_candidate_id, str) and selected_candidate_id
            else None
        )
        runs.append(
            {
                "run_id": run_id,
                "state": payload.get("state", payload.get("status")),
                "frozen_spec_id": frozen_spec_id,
                "frozen_spec_present": bool(frozen),
                "max_parallel": budget.get("max_parallel"),
                "worker_host": strategy.get("worker_host"),
                "orchestration_mode": strategy.get("orchestration_mode"),
                "worker_budget": worker_budget,
                "strategy_config": strategy_config,
                "acceptance_view_contract": acceptance_contract,
                "evidence_annotator_spec": evidence_annotator_spec,
                "evidence_annotations": annotations,
                "process_visible_verifiers": process_verifiers,
                "promotion_visible_verifiers": promotion_verifiers,
                "visible_verifier_integrity": verifier_integrity,
                "promotion_visible_test": promotion_visible_test,
                "candidate_count": len(candidates),
                "agent_session_count": len(sessions),
                "bound_session_count": len(bound_sessions),
                "bound_candidate_ids": sorted(bound_counts),
                "bound_session_counts_by_candidate": dict(sorted(bound_counts.items())),
                "verifier_candidate_ids": sorted(verifier_candidate_ids),
                "selected_candidate_id": selected_candidate_id,
                "promotion_artifact": (
                    str(promotion.relative_to(root))
                    if promotion is not None and promotion.is_file()
                    else None
                ),
            }
        )

    active_pool_jobs = []
    for path in sorted((root / "host-pools" / "pi").glob("pool_*/jobs/job_*/job.json")):
        job = _read_object(path)
        if job.get("status") in ACTIVE_POOL_STATES:
            active_pool_jobs.append(
                {
                    "pool_id": job.get("pool_id"),
                    "job_id": job.get("job_id"),
                    "candidate_id": job.get("candidate_id"),
                    "status": job.get("status"),
                }
            )

    selected_run = runs[0] if len(runs) == 1 else None
    counts = (
        selected_run.get("bound_session_counts_by_candidate", {})
        if selected_run is not None
        else {}
    )
    exact_one_session_per_candidate = bool(
        len(counts) == expected_k and all(value == 1 for value in counts.values())
    )
    acceptance_contract = (
        selected_run.get("acceptance_view_contract") if selected_run else None
    )
    acceptance_criteria = (
        acceptance_contract.get("criteria")
        if isinstance(acceptance_contract, dict)
        and isinstance(acceptance_contract.get("criteria"), list)
        else []
    )
    expected_criterion_ids = [
        str(item.get("id"))
        for item in acceptance_criteria
        if isinstance(item, dict) and item.get("id")
    ]
    acceptance_contract_passed = bool(
        (
            expected_acceptance_view_enabled
            and 3 <= len(acceptance_criteria) <= 8
            and len(expected_criterion_ids) == len(acceptance_criteria)
            and len(set(expected_criterion_ids)) == len(expected_criterion_ids)
        )
        or (not expected_acceptance_view_enabled and acceptance_contract is None)
    )
    annotations = (
        selected_run.get("evidence_annotations", {}) if selected_run else {}
    )
    annotation_entries = (
        annotations.get("entries", []) if isinstance(annotations, dict) else []
    )

    def acceptance_ids(entry: dict[str, Any]) -> list[str] | None:
        view = entry.get("view") if isinstance(entry.get("view"), dict) else {}
        assessment = (
            view.get("acceptance_view")
            if isinstance(view.get("acceptance_view"), dict)
            else None
        )
        if assessment is None:
            return None
        criteria = assessment.get("criteria")
        if not isinstance(criteria, list):
            return []
        return [
            str(item.get("criterion_id"))
            for item in criteria
            if isinstance(item, dict) and item.get("criterion_id")
        ]

    annotations_passed = bool(
        not expected_evidence_annotator_enabled
        or (
            annotations.get("all_completed") is True
            and annotation_entries
            and all(
                entry.get("annotator_host") == "codex"
                for entry in annotation_entries
            )
            and all(
                acceptance_ids(entry) == expected_criterion_ids
                if expected_acceptance_view_enabled
                else acceptance_ids(entry) is None
                for entry in annotation_entries
            )
        )
    )
    checks = {
        "durable_state": _check(True, root.is_dir(), root.is_dir()),
        "terminal_goal": _check(
            "exactly one complete Goal Plus record",
            [item.get("status") for item in goal_records],
            len(goal_records) == 1 and len(complete_goals) == 1,
        ),
        "linked_search_run": _check(1, len(runs), len(runs) == 1),
        "frozen_spec": _check(
            True,
            selected_run.get("frozen_spec_present") if selected_run else False,
            bool(selected_run and selected_run.get("frozen_spec_present")),
        ),
        "max_parallel": _check(
            expected_k,
            selected_run.get("max_parallel") if selected_run else None,
            bool(selected_run and selected_run.get("max_parallel") == expected_k),
        ),
        "worker_topology": _check(
            f"{expected_worker_host}/parallel_loops",
            (
                f"{selected_run.get('worker_host')}/"
                f"{selected_run.get('orchestration_mode')}"
                if selected_run
                else None
            ),
            bool(
                selected_run
                and selected_run.get("worker_host") == expected_worker_host
                and selected_run.get("orchestration_mode") == "parallel_loops"
            ),
        ),
        "worker_runtime": _check(
            expected_worker_runtime_seconds,
            (
                selected_run.get("worker_budget", {}).get("max_runtime_seconds")
                if selected_run
                else None
            ),
            bool(
                selected_run
                and selected_run.get("worker_budget", {}).get(
                    "max_runtime_seconds"
                )
                == expected_worker_runtime_seconds
            ),
        ),
        "closeout_reserve": _check(
            expected_closeout_reserve_seconds,
            (
                selected_run.get("strategy_config", {}).get(
                    "closeout_reserve_seconds"
                )
                if selected_run
                else None
            ),
            bool(
                selected_run
                and selected_run.get("strategy_config", {}).get(
                    "closeout_reserve_seconds"
                )
                == expected_closeout_reserve_seconds
            ),
        ),
        "visible_verifiers": _check(
            "ranking process and promotion wrappers",
            (
                {
                    "process": selected_run.get("process_visible_verifiers"),
                    "promotion": selected_run.get("promotion_visible_verifiers"),
                }
                if selected_run
                else None
            ),
            bool(
                selected_run
                and selected_run.get("process_visible_verifiers", {}).get("passed")
                and selected_run.get("promotion_visible_verifiers", {}).get("passed")
            ),
        ),
        "visible_verifier_integrity": _check(
            expected_visible_verifier_sha256(),
            (
                selected_run.get("visible_verifier_integrity")
                if selected_run
                else None
            ),
            bool(
                selected_run
                and selected_run.get("visible_verifier_integrity", {}).get("passed")
            ),
        ),
        "promotion_visible_test": _check(
            "promotion gate visible_test_score=1.0",
            selected_run.get("promotion_visible_test") if selected_run else None,
            bool(
                selected_run
                and selected_run.get("promotion_visible_test", {}).get("passed")
            ),
        ),
        "acceptance_view_contract": _check(
            (
                "3..8 frozen task-specific criteria"
                if expected_acceptance_view_enabled
                else "disabled"
            ),
            acceptance_contract,
            acceptance_contract_passed,
        ),
        "global_evidence_view": _check(
            (
                "completed descriptions plus Acceptance View"
                if expected_acceptance_view_enabled
                else (
                    "completed descriptions"
                    if expected_evidence_annotator_enabled
                    else "disabled"
                )
            ),
            annotations,
            annotations_passed,
        ),
        "view_agent_contract": _check(
            (
                "independent codex host"
                if expected_evidence_annotator_enabled
                else "disabled"
            ),
            selected_run.get("evidence_annotator_spec") if selected_run else None,
            bool(
                not expected_evidence_annotator_enabled
                or (
                    selected_run
                    and isinstance(
                        selected_run.get("evidence_annotator_spec"), dict
                    )
                    and selected_run["evidence_annotator_spec"].get("host")
                    == "codex"
                )
            ),
        ),
        "candidates": _check(
            expected_k,
            selected_run.get("candidate_count") if selected_run else 0,
            bool(selected_run and selected_run.get("candidate_count") == expected_k),
        ),
        "bound_pi_worker_sessions": _check(
            expected_k,
            selected_run.get("bound_session_count") if selected_run else 0,
            bool(
                selected_run
                and selected_run.get("bound_session_count") == expected_k
                and exact_one_session_per_candidate
            ),
        ),
        "worker_verifier_candidates": _check(
            expected_k,
            len(selected_run.get("verifier_candidate_ids", [])) if selected_run else 0,
            bool(
                selected_run
                and len(selected_run.get("verifier_candidate_ids", [])) == expected_k
            ),
        ),
        "promotion": _check(
            "promoted artifact",
            (
                {
                    "state": selected_run.get("state"),
                    "candidate_id": selected_run.get("selected_candidate_id"),
                    "artifact": selected_run.get("promotion_artifact"),
                }
                if selected_run
                else None
            ),
            bool(
                selected_run
                and selected_run.get("state") == "promoted"
                and selected_run.get("selected_candidate_id")
                and selected_run.get("promotion_artifact")
            ),
        ),
        "active_pi_pool_jobs": _check(0, len(active_pool_jobs), not active_pool_jobs),
    }
    failed = [name for name, check in checks.items() if not check["passed"]]
    return {
        "root": str(root),
        "exists": root.is_dir(),
        "goals": goal_records,
        "runs": runs,
        "active_pi_pool_jobs": active_pool_jobs,
        "actual_subagent_count": (
            int(selected_run.get("bound_session_count") or 0) if selected_run else 0
        ),
        "worker_usage": _usage_from_sessions(all_bound_sessions),
        "evidence_annotator_usage": (
            selected_run.get("evidence_annotations", {}).get("usage", {})
            if selected_run
            else {"coverage": "unavailable"}
        ),
        "completion": {
            "required": True,
            "passed": not failed,
            "expected_k": expected_k,
            "checks": checks,
            "reason": (
                None
                if not failed
                else "Goal Plus completion evidence failed: " + ", ".join(failed)
            ),
        },
    }

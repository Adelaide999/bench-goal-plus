#!/usr/bin/env python3
"""Benchmark-owned Bubblewrap launcher for Goal Plus Pi workers."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import signal
import socketserver
import stat
import subprocess
import sys
import threading
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

GOAL_PLUS_WORKER_LAUNCHER_ENV = "GOAL_PLUS_PI_WORKER_LAUNCHER"
SANDBOX_POLICY_ENV = "BENCH_GOAL_PLUS_PI_SANDBOX"
TOOL_SOCKET_ENV = "BENCH_GOAL_PLUS_PI_TOOL_SOCKET"
LAUNCH_CONTEXT_VERSION = 1
_MAX_PROXY_REQUEST_BYTES = 1024 * 1024
_MAX_UNIX_SOCKET_PATH_BYTES = 103
_ENV_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_PATH_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
_GIT_COMMIT = re.compile(r"^[0-9a-f]{40,64}$")
_RESERVED_ENV_NAMES = {
    "GIT_DIR",
    "GIT_OPTIONAL_LOCKS",
    "GIT_WORK_TREE",
    "HOME",
    "PATH",
    "TMPDIR",
    GOAL_PLUS_WORKER_LAUNCHER_ENV,
    SANDBOX_POLICY_ENV,
    TOOL_SOCKET_ENV,
}
_WORKER_TOOLS = {
    "search_get_agent_context",
    "search_get_global_evidence",
    "search_stage_shared_tool",
    "search_copy_shared_tool",
    "search_get_evidence_detail",
    "search_run_verifier",
    "search_list_iterations",
}
_SESSION_SCOPED_TOOLS = _WORKER_TOOLS - {"search_list_iterations"}
_TOOL_PROXY_BIN = Path(__file__).resolve().parent / "bin" / "goal-plus-pi-tool"
_SANDBOX_TOOL_BIN = Path("/opt/bench-goal-plus/bin")
_BLIND_PUBLIC_METRIC = "format_valid"
_BLIND_RESPONSE_REJECTED = {
    "ok": False,
    "error": "blind worker tool response is unavailable",
}
_BLIND_BLOCKED_TOOLS = {
    "search_copy_shared_tool",
    "search_get_evidence_detail",
    "search_stage_shared_tool",
}
_BLIND_CONTEXT_SOURCE_FIELDS = {
    "agent_session_id",
    "best_iteration",
    "candidate_id",
    "candidate_task",
    "directive",
    "evaluation_mode",
    "host",
    "host_handle",
    "iteration_count",
    "latest_result",
    "metric_direction",
    "metric_name",
    "model_provenance",
    "objective",
    "recent_iterations",
    "result_count",
    "results_tsv",
    "resume",
    "run_budget",
    "run_id",
    "selected_model",
    "supplemental_evaluation_enabled",
    "tool_family_catalog",
    "workspace",
}
_BLIND_CANDIDATE_TASK_SOURCE_FIELDS = {
    "allowed_files",
    "base_candidate_id",
    "candidate_id",
    "denied_files",
    "expected_artifacts",
    "hypothesis",
    "instructions",
    "model_provenance",
    "parent_candidate_ids",
    "parent_id",
    "plan_id",
    "proposal",
    "run_id",
    "selected_model",
    "share_out_dir",
    "stop_conditions",
    "strategy_metadata",
    "workspace",
    "workspace_backend",
    "workspace_base_revision",
    "workspace_branch",
}
_BLIND_CANDIDATE_TASK_OUTPUT_FIELDS = {
    "allowed_files",
    "candidate_id",
    "denied_files",
    "expected_artifacts",
    "run_id",
    "workspace",
}
_BLIND_VERIFIER_SOURCE_FIELDS = {
    "agent_session_id",
    "aggregate_score",
    "best_git_head",
    "best_iteration",
    "candidate_id",
    "changed_outside_allowed",
    "commit",
    "disposition",
    "global_evidence_entry_count",
    "global_evidence_injected",
    "global_evidence_snapshot",
    "global_evidence_warning",
    "hardcoding_suspected",
    "iteration",
    "parent_id",
    "process_passed",
    "promotion_passed",
    "run_id",
    "shared_tool_consumed_entries",
    "shared_tool_deduplicated_entries",
    "shared_tool_errors",
    "shared_tool_publish_status",
    "shared_tool_staged_bytes",
    "shared_tool_staged_entries",
    "shared_tool_staged_file_count",
    "state",
    "toolization_advisories",
    "toolization_decision",
    "touched_denied_files",
    "validity_passed",
    "verifier_results",
    "workspace_git_head_after_settlement",
}
_BLIND_VERIFIER_RECEIPT_FIELDS = {
    "agent_session_id",
    "candidate_id",
    "commit",
    "iteration",
    "run_id",
    "state",
}
_BLIND_ITERATION_SOURCE_FIELDS = {
    "adopted_tools",
    "adoption_confounded",
    "adapter_version",
    "agent_session_id",
    "artifact_hash",
    "attempt_base_git_head",
    "attempt_changed_files",
    "candidate_id",
    "changed_files",
    "changed_outside_allowed",
    "commit",
    "created_at",
    "disposition",
    "exact_model_ref",
    "failure_class",
    "git_artifact_clean",
    "git_head",
    "git_status",
    "hypothesis",
    "iteration",
    "ledger_git_head",
    "log_paths",
    "metrics",
    "model_provenance",
    "process_passed",
    "restored_to_git_head",
    "restored_to_iteration",
    "run_id",
    "score",
    "selected_model",
    "shared_tool_consumed_entries",
    "shared_tool_deduplicated_entries",
    "shared_tool_errors",
    "shared_tool_publish_status",
    "shared_tool_staged_bytes",
    "shared_tool_staged_entries",
    "shared_tool_staged_file_count",
    "shared_tools",
    "state",
    "summary",
    "toolization_advisories",
    "toolization_decision",
    "touched_denied_files",
    "workspace_git_head_after_settlement",
}
_BLIND_ITERATION_RECEIPT_FIELDS = {
    "agent_session_id",
    "candidate_id",
    "commit",
    "iteration",
    "run_id",
    "state",
}
_BLIND_ITERATION_LEGACY_FIELDS = _BLIND_ITERATION_SOURCE_FIELDS - {
    "candidate_id",
    "commit",
    "run_id",
    "state",
}
_INVALID_BLIND_RESPONSE = object()


@dataclass(frozen=True)
class LaunchContext:
    run_id: str
    candidate_id: str
    agent_session_id: str
    workspace: Path

    @classmethod
    def from_json(cls, raw: str) -> LaunchContext:
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid worker launch context JSON: {exc}") from exc
        if not isinstance(payload, dict):
            raise TypeError("worker launch context must be a JSON object")
        expected = {
            "schema_version",
            "run_id",
            "candidate_id",
            "agent_session_id",
            "workspace",
        }
        if set(payload) != expected:
            raise ValueError(
                "worker launch context fields do not match schema version 1"
            )
        if payload["schema_version"] != LAUNCH_CONTEXT_VERSION:
            raise ValueError(
                f"unsupported worker launch context version: {payload['schema_version']!r}"
            )
        values = {
            name: payload[name]
            for name in ("run_id", "candidate_id", "agent_session_id", "workspace")
        }
        if any(not isinstance(value, str) or not value for value in values.values()):
            raise ValueError(
                "worker launch context identity fields must be non-empty strings"
            )
        for name in ("run_id", "candidate_id"):
            if not _PATH_ID.fullmatch(values[name]) or values[name] in {".", ".."}:
                raise ValueError(
                    f"worker launch context {name} is not a safe path identity"
                )
        workspace = Path(values["workspace"])
        if not workspace.is_absolute() or not workspace.is_dir():
            raise ValueError(
                "worker launch workspace must be an existing absolute path"
            )
        return cls(
            run_id=values["run_id"],
            candidate_id=values["candidate_id"],
            agent_session_id=values["agent_session_id"],
            workspace=workspace.resolve(),
        )


@dataclass(frozen=True)
class SandboxPolicy:
    engine: str
    workspace_access: str
    read_only_workspace_paths: tuple[str, ...]
    writable_workspace_paths: tuple[str, ...]
    pass_env: tuple[str, ...]
    evaluation_mode: str = "visible"

    @classmethod
    def from_environment(cls, environment: Mapping[str, str]) -> SandboxPolicy:
        raw = environment.get(SANDBOX_POLICY_ENV)
        if raw is None:
            raise RuntimeError(f"{SANDBOX_POLICY_ENV} is required")
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{SANDBOX_POLICY_ENV} must be valid JSON: {exc}") from exc
        if not isinstance(payload, dict):
            raise TypeError(f"{SANDBOX_POLICY_ENV} must be a JSON object")
        allowed = {
            "engine",
            "evaluation_mode",
            "workspace_access",
            "read_only_workspace_paths",
            "writable_workspace_paths",
            "pass_env",
        }
        unknown = sorted(set(payload) - allowed)
        if unknown:
            raise ValueError(
                f"{SANDBOX_POLICY_ENV} has unsupported fields: {', '.join(unknown)}"
            )
        engine = payload.get("engine")
        if engine != "bubblewrap":
            raise ValueError(
                f"{SANDBOX_POLICY_ENV}.engine must be 'bubblewrap', got {engine!r}"
            )
        evaluation_mode = payload.get("evaluation_mode", "visible")
        if evaluation_mode not in {"visible", "blind"}:
            raise ValueError(
                f"{SANDBOX_POLICY_ENV}.evaluation_mode must be 'visible' or "
                f"'blind', got {evaluation_mode!r}"
            )
        workspace_access = payload.get("workspace_access")
        if workspace_access != "read_only":
            raise ValueError(
                f"{SANDBOX_POLICY_ENV}.workspace_access must be 'read_only', "
                f"got {workspace_access!r}"
            )
        read_only_paths = _workspace_path_list(
            payload.get("read_only_workspace_paths", []),
            field="read_only_workspace_paths",
        )
        writable_paths = _workspace_path_list(
            payload.get("writable_workspace_paths", []),
            field="writable_workspace_paths",
        )
        for read_only in read_only_paths:
            for writable in writable_paths:
                if _relative_paths_overlap(read_only, writable):
                    raise ValueError(
                        "sandbox read-only and writable workspace paths overlap: "
                        f"{read_only!r} and {writable!r}"
                    )
        for index, left in enumerate(writable_paths):
            for right in writable_paths[index + 1 :]:
                if _relative_paths_overlap(left, right):
                    raise ValueError(
                        "sandbox writable workspace paths overlap: "
                        f"{left!r} and {right!r}"
                    )
        for value in writable_paths:
            if value == ".tmp" or value.startswith(".tmp/"):
                raise ValueError(
                    "writable_workspace_paths must not override launcher-owned .tmp"
                )
        pass_env = _string_list(payload.get("pass_env", []), field="pass_env")
        invalid_env = [name for name in pass_env if not _ENV_NAME.fullmatch(name)]
        if invalid_env:
            raise ValueError(f"invalid pass_env name: {invalid_env[0]!r}")
        reserved_env = sorted(set(pass_env) & _RESERVED_ENV_NAMES)
        if reserved_env:
            raise ValueError(
                f"{SANDBOX_POLICY_ENV}.pass_env cannot override reserved variables: "
                + ", ".join(reserved_env)
            )
        return cls(
            engine=engine,
            workspace_access=workspace_access,
            read_only_workspace_paths=tuple(read_only_paths),
            writable_workspace_paths=tuple(writable_paths),
            pass_env=tuple(pass_env),
            evaluation_mode=evaluation_mode,
        )


@dataclass(frozen=True)
class PrivateGitAdmin:
    git_dir: Path
    object_dir: Path
    work_tree: Path


def _string_list(value: Any, *, field: str) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ValueError(f"{SANDBOX_POLICY_ENV}.{field} must be a list of strings")
    if len(value) != len(set(value)):
        raise ValueError(f"{SANDBOX_POLICY_ENV}.{field} must not contain duplicates")
    return value


def _workspace_path_list(value: Any, *, field: str) -> list[str]:
    paths = _string_list(value, field=field)
    for item in paths:
        candidate = Path(item)
        if candidate.is_absolute() or item in {"", "."} or ".." in candidate.parts:
            raise ValueError(
                f"{field} entries must be non-empty relative paths without '..': "
                f"{item!r}"
            )
    return paths


def _relative_paths_overlap(left: str, right: str) -> bool:
    left_path = Path(left)
    right_path = Path(right)
    return (
        left_path == right_path
        or left_path in right_path.parents
        or right_path in left_path.parents
    )


def _blind_context_response(
    result: Any, context: LaunchContext
) -> dict[str, Any] | object:
    if not isinstance(result, dict) or not set(result) <= _BLIND_CONTEXT_SOURCE_FIELDS:
        return _INVALID_BLIND_RESPONSE
    required = {
        "agent_session_id",
        "run_id",
        "candidate_id",
        "workspace",
        "candidate_task",
        "metric_name",
        "metric_direction",
    }
    if not required <= set(result):
        return _INVALID_BLIND_RESPONSE
    if (
        result["agent_session_id"] != context.agent_session_id
        or result["run_id"] != context.run_id
        or result["candidate_id"] != context.candidate_id
        or result["workspace"] != str(context.workspace)
        or result.get("evaluation_mode", "blind") != "blind"
        or result["metric_name"] != _BLIND_PUBLIC_METRIC
        or result["metric_direction"] != "maximize"
    ):
        return _INVALID_BLIND_RESPONSE

    candidate_task = result["candidate_task"]
    if (
        not isinstance(candidate_task, dict)
        or not set(candidate_task) <= _BLIND_CANDIDATE_TASK_SOURCE_FIELDS
        or candidate_task.get("run_id") != context.run_id
        or candidate_task.get("candidate_id") != context.candidate_id
        or candidate_task.get("workspace") != str(context.workspace)
    ):
        return _INVALID_BLIND_RESPONSE
    projected_task: dict[str, Any] = {}
    for key in _BLIND_CANDIDATE_TASK_OUTPUT_FIELDS:
        if key not in candidate_task:
            continue
        value = candidate_task[key]
        if key in {
            "allowed_files",
            "denied_files",
            "expected_artifacts",
            "instructions",
            "parent_candidate_ids",
        }:
            if not isinstance(value, list) or any(
                not isinstance(item, str) for item in value
            ):
                return _INVALID_BLIND_RESPONSE
        elif value is not None and not isinstance(value, str):
            return _INVALID_BLIND_RESPONSE
        projected_task[key] = value

    projected: dict[str, Any] = {
        "agent_session_id": context.agent_session_id,
        "run_id": context.run_id,
        "candidate_id": context.candidate_id,
        "workspace": str(context.workspace),
        "candidate_task": projected_task,
    }
    projected["metric_name"] = _BLIND_PUBLIC_METRIC
    projected["metric_direction"] = "maximize"
    return projected


def _blind_verifier_receipt(
    result: Any, context: LaunchContext
) -> dict[str, Any] | object:
    if isinstance(result, dict) and set(result) == _BLIND_VERIFIER_RECEIPT_FIELDS:
        if (
            result["run_id"] != context.run_id
            or result["candidate_id"] != context.candidate_id
            or result["agent_session_id"] != context.agent_session_id
            or type(result["iteration"]) is not int
            or result["iteration"] < 1
            or not isinstance(result["commit"], str)
            or _GIT_COMMIT.fullmatch(result["commit"]) is None
            or result["state"] != "recorded"
        ):
            return _INVALID_BLIND_RESPONSE
        return dict(result)
    if isinstance(result, dict) and (
        set(result)
        & (_BLIND_VERIFIER_RECEIPT_FIELDS - {"run_id", "candidate_id"})
    ):
        return _INVALID_BLIND_RESPONSE
    if (
        not isinstance(result, dict)
        or not set(result) <= _BLIND_VERIFIER_SOURCE_FIELDS
        or result.get("run_id") != context.run_id
        or result.get("candidate_id") != context.candidate_id
    ):
        return _INVALID_BLIND_RESPONSE
    return {
        "run_id": context.run_id,
        "candidate_id": context.candidate_id,
        "recorded": True,
    }


def _blind_iteration_receipts(
    result: Any, context: LaunchContext
) -> list[dict[str, Any]] | object:
    if not isinstance(result, list):
        return _INVALID_BLIND_RESPONSE
    receipts: list[dict[str, Any]] = []
    for item in result:
        if isinstance(item, dict) and set(item) == _BLIND_ITERATION_RECEIPT_FIELDS:
            if (
                item["run_id"] != context.run_id
                or item["candidate_id"] != context.candidate_id
                or item["agent_session_id"] != context.agent_session_id
                or type(item["iteration"]) is not int
                or item["iteration"] < 1
                or not isinstance(item["commit"], str)
                or _GIT_COMMIT.fullmatch(item["commit"]) is None
                or item["state"] != "recorded"
            ):
                return _INVALID_BLIND_RESPONSE
            receipts.append(dict(item))
            continue
        if (
            not isinstance(item, dict)
            or not set(item) <= _BLIND_ITERATION_LEGACY_FIELDS
        ):
            return _INVALID_BLIND_RESPONSE
        iteration = item.get("iteration")
        if type(iteration) is not int or iteration < 1:
            return _INVALID_BLIND_RESPONSE
        receipts.append({"iteration": iteration, "recorded": True})
    return receipts


def _blind_tool_response(
    tool: str, result: Any, context: LaunchContext
) -> Any:
    if tool == "search_get_agent_context":
        return _blind_context_response(result, context)
    if tool == "search_run_verifier":
        return _blind_verifier_receipt(result, context)
    if tool == "search_list_iterations":
        return _blind_iteration_receipts(result, context)
    if tool == "search_get_global_evidence":
        return [] if result == [] else _INVALID_BLIND_RESPONSE
    return _INVALID_BLIND_RESPONSE


class _ThreadingUnixServer(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    daemon_threads = True


class WorkerToolProxy:
    def __init__(
        self,
        *,
        root: Path,
        context: LaunchContext,
        socket_dir: Path,
        evaluation_mode: str = "visible",
    ) -> None:
        self.root = root
        self.context = context
        self.socket_dir = socket_dir
        self.socket_path = socket_dir / "tool.sock"
        if evaluation_mode not in {"visible", "blind"}:
            raise ValueError(f"unsupported proxy evaluation mode: {evaluation_mode}")
        self.evaluation_mode = evaluation_mode
        self._server: _ThreadingUnixServer | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self.socket_dir.mkdir(parents=True, mode=0o700, exist_ok=False)
        proxy = self

        class Handler(socketserver.StreamRequestHandler):
            def handle(self) -> None:
                raw = self.rfile.readline(_MAX_PROXY_REQUEST_BYTES + 1)
                if len(raw) > _MAX_PROXY_REQUEST_BYTES:
                    response = {"ok": False, "error": "proxy request is too large"}
                else:
                    try:
                        request = json.loads(raw.decode("utf-8"))
                        response = proxy.dispatch(request)
                    except Exception as exc:  # noqa: BLE001
                        response = (
                            dict(_BLIND_RESPONSE_REJECTED)
                            if proxy.evaluation_mode == "blind"
                            else {
                                "ok": False,
                                "error": str(exc),
                                "error_type": type(exc).__name__,
                            }
                        )
                self.wfile.write(
                    (json.dumps(response, ensure_ascii=False) + "\n").encode("utf-8")
                )

        self._server = _ThreadingUnixServer(str(self.socket_path), Handler)
        os.chmod(self.socket_path, 0o600)
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            name=f"zsoft-pi-tool-proxy-{self.context.agent_session_id}",
            daemon=True,
        )
        self._thread.start()

    def dispatch(self, request: Any) -> dict[str, Any]:
        if not isinstance(request, dict):
            raise TypeError("proxy request must be a JSON object")
        tool = request.get("tool")
        args = request.get("args")
        if tool not in _WORKER_TOOLS:
            raise PermissionError(f"Pi worker proxy does not allow tool {tool!r}")
        if not isinstance(args, dict):
            raise TypeError("proxy tool args must be a JSON object")
        self._authorize(str(tool), args)
        if self.evaluation_mode == "blind" and tool in _BLIND_BLOCKED_TOOLS:
            return dict(_BLIND_RESPONSE_REJECTED)
        from goal_plus.pi_tool import call_pi_tool

        try:
            result = call_pi_tool(self.root, str(tool), args)
        except Exception:  # blind workers must not receive raw host exceptions
            if self.evaluation_mode == "blind":
                return dict(_BLIND_RESPONSE_REJECTED)
            raise
        if self.evaluation_mode == "blind":
            result = _blind_tool_response(str(tool), result, self.context)
            if result is _INVALID_BLIND_RESPONSE:
                return dict(_BLIND_RESPONSE_REJECTED)
        return {
            "ok": True,
            "result": result,
        }

    def _authorize(self, tool: str, args: dict[str, Any]) -> None:
        if (
            tool in _SESSION_SCOPED_TOOLS
            and args.get("agent_session_id") != self.context.agent_session_id
        ):
            raise PermissionError("Pi worker proxy requires the bound agent_session_id")
        if "run_id" in args and args["run_id"] != self.context.run_id:
            raise PermissionError("Pi worker proxy rejected a different run_id")
        if (
            tool in {"search_run_verifier", "search_list_iterations"}
            and args.get("candidate_id") != self.context.candidate_id
        ):
            raise PermissionError("Pi worker proxy rejected a different candidate_id")
        if (
            self.evaluation_mode == "blind"
            and tool == "search_list_iterations"
            and args.get("agent_session_id") != self.context.agent_session_id
        ):
            raise PermissionError(
                "blind Pi iteration listing requires the bound agent_session_id"
            )
        if tool == "search_run_verifier" and args.get("scope", "process") != "process":
            raise PermissionError("Pi workers may only run process verifiers")

    def close(self) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
            self._server = None
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None
        self.socket_path.unlink(missing_ok=True)
        try:
            self.socket_dir.rmdir()
        except OSError:
            pass


class BubblewrapWorker:
    def __init__(
        self,
        *,
        context: LaunchContext,
        policy: SandboxPolicy,
        command: list[str],
        environment: Mapping[str, str],
    ) -> None:
        self.context = context
        self.policy = policy
        self.command = command
        self.environment = dict(environment)
        self.root = _runtime_root(self.environment, context)
        proxy_base = _worker_proxy_base(self.environment)
        self.proxy = WorkerToolProxy(
            root=self.root,
            context=context,
            socket_dir=proxy_base / f"bgp-pi-{uuid.uuid4().hex[:16]}",
            evaluation_mode=policy.evaluation_mode,
        )
        self.private_git_admin: PrivateGitAdmin | None = None

    def prepare(self) -> tuple[list[str], dict[str, str]]:
        try:
            self.proxy.start()
            return self._build_command()
        except Exception:
            self.close()
            raise

    def _build_command(self) -> tuple[list[str], dict[str, str]]:
        if not self.command:
            raise ValueError("external worker launcher requires an original command")
        bwrap = shutil.which("bwrap", path=self.environment.get("PATH"))
        if bwrap is None:
            raise FileNotFoundError("ZSoft Pi worker launcher requires bwrap on PATH")
        executable = shutil.which(self.command[0], path=self.environment.get("PATH"))
        if executable is None:
            raise FileNotFoundError(f"Pi executable not found: {self.command[0]}")
        executable_path = Path(executable).absolute()
        pi_runtime = _executable_runtime_root(executable_path)
        extension = _command_path_argument(self.command, "-e")
        extension_bundle = extension.parent
        session_root = _command_path_argument(self.command, "--session-dir")
        session_id = _command_argument(self.command, "--session-id")
        if not extension.is_file():
            raise FileNotFoundError(f"Pi extension not found: {extension}")
        if _inside(extension_bundle, self.root) or _inside(self.root, extension_bundle):
            raise ValueError("Pi extension bundle must be disjoint from GOAL_PLUS_ROOT")
        if self.root not in session_root.parents:
            raise ValueError(
                "Pi worker session directory must live under GOAL_PLUS_ROOT"
            )
        isolated_session = session_root / _safe_name(session_id)
        if isolated_session.is_symlink():
            raise RuntimeError("Pi worker session directory must not be a symlink")
        isolated_session.mkdir(parents=True, exist_ok=True)
        if (
            not isolated_session.is_dir()
            or session_root not in isolated_session.resolve(strict=True).parents
        ):
            raise RuntimeError(
                "Pi worker session directory escapes its declared session root"
            )
        command = _replace_command_argument(
            self.command,
            "--session-dir",
            str(isolated_session),
        )
        if not _TOOL_PROXY_BIN.is_file() or not os.access(_TOOL_PROXY_BIN, os.X_OK):
            raise FileNotFoundError(
                f"worker tool proxy is not executable: {_TOOL_PROXY_BIN}"
            )

        args = [
            bwrap,
            "--die-with-parent",
            "--new-session",
            "--unshare-all",
            "--share-net",
            "--unshare-user",
            "--disable-userns",
            "--cap-drop",
            "ALL",
            "--hostname",
            "zsoft-goal-plus-worker",
            "--clearenv",
            "--proc",
            "/proc",
            "--dev",
            "/dev",
            "--tmpfs",
            "/tmp",
            "--dir",
            "/run",
            "--dir",
            "/home",
            "--dir",
            "/home/pi",
        ]
        created = {"/proc", "/dev", "/tmp", "/run", "/home", "/home/pi"}
        _mount_system(args)
        if not _is_system_path(pi_runtime):
            _add_bind(args, pi_runtime, pi_runtime, readonly=True, created=created)
        _add_tmpfs(args, self.root, created)
        protected_paths = _validated_workspace_paths(
            self.context.workspace,
            self.policy.read_only_workspace_paths,
            access="read-only",
            validate_links=True,
        )
        writable_paths = _validated_workspace_paths(
            self.context.workspace,
            self.policy.writable_workspace_paths,
            access="writable",
            validate_links=False,
        )
        scratch = _prepare_workspace_scratch(self.context.workspace)
        self.private_git_admin = _prepare_private_git_admin(
            self.context.workspace,
            self.root
            / "worker-sandbox-state"
            / self.context.run_id
            / self.context.candidate_id
            / "git-admin",
        )
        if self.private_git_admin is not None:
            _add_bind(
                args,
                self.private_git_admin.object_dir,
                self.private_git_admin.object_dir,
                readonly=True,
                created=created,
            )
            _add_bind(
                args,
                self.private_git_admin.git_dir,
                self.private_git_admin.git_dir,
                readonly=False,
                created=created,
            )
        _add_bind(
            args,
            self.context.workspace,
            self.context.workspace,
            readonly=True,
            created=created,
        )
        _add_bind(
            args,
            isolated_session,
            isolated_session,
            readonly=False,
            created=created,
        )
        _add_bind(
            args,
            self.proxy.socket_dir,
            self.proxy.socket_dir,
            readonly=False,
            created=created,
        )
        _add_bind(
            args,
            extension_bundle,
            extension_bundle,
            readonly=True,
            created=created,
        )
        _add_bind(
            args,
            _TOOL_PROXY_BIN.parent,
            _SANDBOX_TOOL_BIN,
            readonly=True,
            created=created,
        )

        pi_home_text = self.environment.get("PI_CODING_AGENT_DIR")
        if not pi_home_text:
            raise RuntimeError("PI_CODING_AGENT_DIR is required for ZSoft Pi workers")
        pi_home = Path(pi_home_text).expanduser().resolve()
        if not pi_home.is_dir():
            raise FileNotFoundError(f"PI_CODING_AGENT_DIR not found: {pi_home}")
        private_pi_home = _prepare_private_pi_home(
            pi_home,
            self.proxy.socket_dir / "pi-home",
        )
        _add_bind(args, private_pi_home, pi_home, readonly=False, created=created)
        private_models = private_pi_home / "models.json"
        if private_models.is_file():
            _add_bind(
                args,
                private_models,
                pi_home / "models.json",
                readonly=True,
                created=created,
            )

        for path in protected_paths:
            _add_bind(args, path, path, readonly=True, created=created)
        for path in writable_paths:
            _add_bind(args, path, path, readonly=False, created=created)
        _add_bind(args, scratch, scratch, readonly=False, created=created)

        sandbox_env = _sandbox_environment(
            self.environment,
            policy=self.policy,
            pi_runtime=pi_runtime,
            socket_path=self.proxy.socket_path,
            private_git_admin=self.private_git_admin,
        )
        for name, value in sandbox_env.items():
            args.extend(["--setenv", name, value])
        args.extend(
            [
                "--chdir",
                str(self.context.workspace),
                "--",
                str(executable_path),
                *command[1:],
            ]
        )
        return args, sandbox_env

    def close(self) -> None:
        self.proxy.close()
        _remove_private_runtime_tree(self.proxy.socket_dir)


def _runtime_root(
    environment: Mapping[str, str],
    context: LaunchContext,
) -> Path:
    value = environment.get("GOAL_PLUS_ROOT")
    if not value:
        raise RuntimeError("GOAL_PLUS_ROOT is required for ZSoft Pi workers")
    root = Path(value).resolve()
    if not root.is_dir():
        raise ValueError("GOAL_PLUS_ROOT must be an existing runtime directory")
    expected_workspace_path = (
        root / "runs" / context.run_id / "workspace" / context.candidate_id
    )
    current = root
    for part in ("runs", context.run_id, "workspace", context.candidate_id):
        current = current / part
        if current.is_symlink():
            raise ValueError("worker runtime identity path must not contain symlinks")
    expected_workspace = expected_workspace_path.resolve(strict=False)
    if (
        not expected_workspace_path.is_dir()
        or context.workspace.resolve(strict=True) != expected_workspace
    ):
        raise ValueError(
            "worker workspace does not match GOAL_PLUS_ROOT identity: "
            f"{expected_workspace}"
        )
    return root


def _worker_proxy_base(environment: Mapping[str, str]) -> Path:
    candidates: list[Path] = []
    configured = environment.get("XDG_RUNTIME_DIR")
    if configured:
        candidates.append(Path(configured).expanduser())
    user_runtime = Path("/run") / "user" / str(os.geteuid())
    if user_runtime not in candidates:
        candidates.append(user_runtime)

    for candidate in candidates:
        if (
            not candidate.is_absolute()
            or candidate.is_symlink()
            or not candidate.is_dir()
        ):
            continue
        metadata = candidate.stat()
        if (
            metadata.st_uid != os.geteuid()
            or stat.S_IMODE(metadata.st_mode) & 0o077
            or not os.access(candidate, os.W_OK | os.X_OK)
        ):
            continue
        base = candidate / "bench-goal-plus"
        if base.is_symlink():
            continue
        base.mkdir(mode=0o700, exist_ok=True)
        base.chmod(0o700)
        sample = base / "bgp-pi-0000000000000000" / "tool.sock"
        if len(os.fsencode(sample)) <= _MAX_UNIX_SOCKET_PATH_BYTES:
            return base
    raise RuntimeError(
        "ZSoft Pi worker launcher requires a private short XDG_RUNTIME_DIR or "
        "/run/user/<uid> for its Unix socket"
    )


def _command_argument(command: list[str], option: str) -> str:
    try:
        index = command.index(option)
        value = command[index + 1]
    except (ValueError, IndexError) as exc:
        raise ValueError(f"Pi worker command is missing {option}") from exc
    if not value:
        raise ValueError(f"Pi worker command has an empty {option}")
    return value


def _command_path_argument(command: list[str], option: str) -> Path:
    path = Path(_command_argument(command, option))
    if not path.is_absolute():
        raise ValueError(f"Pi worker command {option} path must be absolute")
    return path.resolve()


def _replace_command_argument(command: list[str], option: str, value: str) -> list[str]:
    result = list(command)
    result[result.index(option) + 1] = value
    return result


def _safe_name(value: str) -> str:
    if not _PATH_ID.fullmatch(value) or value in {".", ".."}:
        raise ValueError("Pi worker session id does not contain a safe path name")
    return value


def _executable_runtime_root(executable: Path) -> Path:
    if executable.parent.name == "bin":
        return executable.parent.parent.resolve()
    return executable.resolve()


def _is_system_path(path: Path) -> bool:
    roots = map(Path, ("/usr", "/bin", "/sbin", "/lib", "/lib64"))
    return any(path == root or root in path.parents for root in roots)


def _mount_system(args: list[str]) -> None:
    args.extend(["--ro-bind", "/usr", "/usr"])
    for value in ("/bin", "/sbin", "/lib", "/lib64"):
        path = Path(value)
        if path.is_symlink():
            args.extend(["--symlink", os.readlink(path), value])
        elif path.exists():
            args.extend(["--ro-bind", value, value])
    args.extend(["--dir", "/etc"])
    for value in (
        "/etc/hosts",
        "/etc/resolv.conf",
        "/etc/nsswitch.conf",
        "/etc/passwd",
        "/etc/group",
        "/etc/localtime",
        "/etc/ssl/certs",
        "/etc/alternatives",
    ):
        if Path(value).exists():
            args.extend(["--ro-bind", value, value])


def _ensure_parent_dirs(args: list[str], destination: Path, created: set[str]) -> None:
    for parent in reversed(destination.parents[:-1]):
        value = str(parent)
        if value != "/" and value not in created:
            args.extend(["--dir", value])
            created.add(value)


def _add_bind(
    args: list[str],
    source: Path,
    destination: Path,
    *,
    readonly: bool,
    created: set[str],
) -> None:
    source = source.resolve()
    destination = destination.absolute()
    _ensure_parent_dirs(args, destination, created)
    args.extend(["--ro-bind" if readonly else "--bind", str(source), str(destination)])
    created.add(str(destination))


def _add_tmpfs(args: list[str], destination: Path, created: set[str]) -> None:
    destination = destination.absolute()
    _ensure_parent_dirs(args, destination, created)
    args.extend(["--tmpfs", str(destination)])
    created.add(str(destination))


def _git_output(cwd: Path, *args: str) -> str | None:
    completed = subprocess.run(
        ["git", "-C", str(cwd), *args],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        return None
    return completed.stdout.strip()


def _inside(path: Path, root: Path) -> bool:
    return path == root or root in path.parents


def _validate_confined_symlinks(root: Path, *, label: str) -> None:
    root = root.absolute()
    if root.is_symlink():
        raise RuntimeError(f"{label} root must not be a symlink")
    resolved_root = root.resolve(strict=True)
    for directory, dirnames, filenames in os.walk(root, followlinks=False):
        parent = Path(directory)
        for name in (*dirnames, *filenames):
            path = parent / name
            if not path.is_symlink():
                continue
            try:
                target = path.resolve(strict=False)
            except RuntimeError as exc:
                raise RuntimeError(
                    f"{label} contains an unresolvable symlink: "
                    f"{path.relative_to(root)}"
                ) from exc
            if not _inside(target, resolved_root):
                raise RuntimeError(
                    f"{label} symlink escapes its root: "
                    f"{path.relative_to(root)} -> {os.readlink(path)}"
                )


def _validated_workspace_paths(
    workspace: Path,
    relative_paths: tuple[str, ...],
    *,
    access: str,
    validate_links: bool,
) -> list[Path]:
    resolved_workspace = workspace.resolve(strict=True)
    result: list[Path] = []
    for relative in relative_paths:
        path = workspace / relative
        if not path.exists():
            raise FileNotFoundError(
                f"sandbox {access} workspace path not found: {relative}"
            )
        if path.is_symlink():
            raise RuntimeError(
                f"sandbox {access} workspace path must not be a symlink: {relative}"
            )
        resolved = path.resolve(strict=True)
        if not _inside(resolved, resolved_workspace):
            raise RuntimeError(
                f"sandbox {access} workspace path escapes the workspace: {relative}"
            )
        if validate_links and path.is_dir():
            _validate_confined_symlinks(
                path,
                label=f"sandbox {access} workspace path {relative}",
            )
        if access == "writable":
            required_access = os.W_OK | (os.X_OK if path.is_dir() else 0)
            if not os.access(path, required_access):
                raise PermissionError(
                    f"sandbox writable workspace path is not writable: {relative}"
                )
        result.append(path)
    return result


def _prepare_workspace_scratch(workspace: Path) -> Path:
    scratch = workspace / ".tmp"
    if scratch.is_symlink():
        raise RuntimeError("launcher-owned workspace .tmp must not be a symlink")
    scratch.mkdir(mode=0o700, exist_ok=True)
    scratch.chmod(0o700)
    if not scratch.is_dir() or not os.access(scratch, os.W_OK | os.X_OK):
        raise PermissionError("launcher-owned workspace .tmp is not writable")
    return scratch


def _remove_private_runtime_tree(path: Path) -> None:
    if path.is_symlink():
        path.unlink()
        return
    if not path.exists() and not path.is_symlink():
        return
    _restore_private_tree_owner_access(path)
    shutil.rmtree(path)


def _restore_private_tree_owner_access(path: Path) -> None:
    mode = path.lstat().st_mode
    if stat.S_ISLNK(mode):
        return
    owner_access = stat.S_IRUSR | stat.S_IWUSR
    if stat.S_ISDIR(mode):
        path.chmod(mode | owner_access | stat.S_IXUSR)
        with os.scandir(path) as entries:
            for entry in entries:
                _restore_private_tree_owner_access(Path(entry.path))
    else:
        path.chmod(mode | owner_access)


def _prepare_private_pi_home(source: Path, destination: Path) -> Path:
    symlink = next((path for path in source.rglob("*") if path.is_symlink()), None)
    if symlink is not None:
        raise RuntimeError(
            "PI_CODING_AGENT_DIR must not contain symlinks: "
            f"{symlink.relative_to(source)}"
        )
    shutil.copytree(source, destination)
    destination.chmod(0o700)
    return destination


def _prepare_private_git_admin(
    workspace: Path,
    destination: Path,
) -> PrivateGitAdmin | None:
    workspace = workspace.resolve()
    head = _git_output(workspace, "rev-parse", "--verify", "HEAD")
    object_dir_text = _git_output(
        workspace,
        "rev-parse",
        "--path-format=absolute",
        "--git-path",
        "objects",
    )
    if not head or object_dir_text is None:
        raise RuntimeError(
            "ZSoft Pi worker sandbox cannot isolate the candidate Git state"
        )
    object_dir = Path(object_dir_text).resolve()
    if not object_dir.is_dir():
        raise FileNotFoundError(
            f"candidate Git object directory not found: {object_dir}"
        )

    if destination.is_symlink():
        raise RuntimeError("candidate-private Git directory must not be a symlink")
    if destination.exists():
        if not destination.is_dir():
            raise RuntimeError("candidate-private Git path is not a directory")
        _validate_confined_symlinks(
            destination,
            label="candidate-private Git directory",
        )
        configured_worktree = _git_output(
            workspace,
            f"--git-dir={destination}",
            "config",
            "--path",
            "core.worktree",
        )
        private_head = _git_output(
            workspace,
            f"--git-dir={destination}",
            "rev-parse",
            "--verify",
            "HEAD",
        )
        alternates = destination / "objects" / "info" / "alternates"
        if (
            configured_worktree is None
            or Path(configured_worktree).resolve() != workspace
            or private_head is None
            or not alternates.is_file()
            or alternates.read_text(encoding="utf-8").strip() != str(object_dir)
        ):
            raise RuntimeError(
                "existing candidate-private Git directory has an invalid identity"
            )
        return PrivateGitAdmin(
            git_dir=destination,
            object_dir=object_dir,
            work_tree=workspace,
        )

    destination.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    if destination.parent.is_symlink():
        raise RuntimeError("candidate-private Git parent must not be a symlink")
    subprocess.run(
        ["git", "init", "--bare", "-q", str(destination)],
        check=True,
        capture_output=True,
        text=True,
    )
    destination.chmod(0o700)
    alternates = destination / "objects" / "info" / "alternates"
    alternates.parent.mkdir(parents=True, exist_ok=True)
    alternates.write_text(f"{object_dir}\n", encoding="utf-8")
    git_command = ["git", f"--git-dir={destination}"]
    for command in (
        [*git_command, "config", "core.bare", "false"],
        [*git_command, "config", "core.worktree", str(workspace)],
        [*git_command, "update-ref", "refs/heads/sandbox", head],
        [*git_command, "symbolic-ref", "HEAD", "refs/heads/sandbox"],
        [*git_command, f"--work-tree={workspace}", "read-tree", "HEAD"],
    ):
        subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
        )
    return PrivateGitAdmin(
        git_dir=destination,
        object_dir=object_dir,
        work_tree=workspace,
    )


def _sandbox_environment(
    environment: Mapping[str, str],
    *,
    policy: SandboxPolicy,
    pi_runtime: Path,
    socket_path: Path,
    private_git_admin: PrivateGitAdmin | None,
) -> dict[str, str]:
    runtime_bin = pi_runtime / "bin" if pi_runtime.is_dir() else pi_runtime.parent
    result = {
        "HOME": "/home/pi",
        "TMPDIR": "/tmp",
        "LANG": environment.get("LANG", "C.UTF-8"),
        "LC_ALL": environment.get("LC_ALL", "C.UTF-8"),
        "TZ": environment.get("TZ", "UTC"),
        "PATH": os.pathsep.join(
            (
                str(_SANDBOX_TOOL_BIN),
                str(runtime_bin),
                "/usr/local/sbin",
                "/usr/local/bin",
                "/usr/sbin",
                "/usr/bin",
                "/sbin",
                "/bin",
            )
        ),
        TOOL_SOCKET_ENV: str(socket_path),
    }
    if private_git_admin is not None:
        result.update(
            {
                "GIT_DIR": str(private_git_admin.git_dir),
                "GIT_WORK_TREE": str(private_git_admin.work_tree),
                "GIT_OPTIONAL_LOCKS": "0",
            }
        )
    inherited_names = {
        "PI_CODING_AGENT_DIR",
        "GOAL_PLUS_PI_ROLE",
        "GOAL_PLUS_PI_MODEL",
        "GOAL_PLUS_PI_WORKER_CONTINUE_UNTIL_MS",
        *policy.pass_env,
    }
    for name in sorted(inherited_names):
        if name in environment:
            result[name] = environment[name]
    return result


def run_launcher(
    context: LaunchContext,
    command: list[str],
    environment: Mapping[str, str],
) -> int:
    policy = SandboxPolicy.from_environment(environment)
    sandbox = BubblewrapWorker(
        context=context,
        policy=policy,
        command=command,
        environment=environment,
    )
    wrapped_command, wrapped_environment = sandbox.prepare()
    process: subprocess.Popen[bytes] | None = None
    previous_handlers: dict[int, Any] = {}

    def stop_child(signum: int, _frame: Any) -> None:
        if process is not None and process.poll() is None:
            process.send_signal(signum)

    try:
        process = subprocess.Popen(
            wrapped_command,
            cwd=context.workspace,
            env=wrapped_environment,
        )
        if threading.current_thread() is threading.main_thread():
            for signum in (signal.SIGTERM, signal.SIGINT):
                previous_handlers[signum] = signal.signal(signum, stop_child)
        returncode = process.wait()
        return returncode if returncode >= 0 else 128 - returncode
    finally:
        for signum, handler in previous_handlers.items():
            signal.signal(signum, handler)
        sandbox.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--context-json", required=True)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    command = list(args.command)
    if command and command[0] == "--":
        command = command[1:]
    try:
        context = LaunchContext.from_json(args.context_json)
        return run_launcher(context, command, os.environ)
    except Exception as exc:  # noqa: BLE001
        print(
            json.dumps(
                {
                    "ok": False,
                    "error": str(exc),
                    "error_type": type(exc).__name__,
                },
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

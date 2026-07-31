"""Host, authentication, Docker, provisioning, and doctor checks."""

from __future__ import annotations

import atexit
import json
import os
import re
import signal
import socket
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

import yaml

from bench_runtime_paths import configure_temp_environment, ensure_temp_root

from . import io
from .context import current_paths
from .profiles import (
    METHODS,
    api_protocol_for_methods,
    load_official_codex_protocol,
    profile_task_protocol,
)


def resolve_agent_api_config(
    env: dict[str, str] | None = None,
    *,
    protocol: str = "openai",
) -> dict[str, str | None]:
    source = os.environ if env is None else env

    def first(names: tuple[str, ...]) -> tuple[str | None, str | None]:
        for name in names:
            value = source.get(name)
            if value:
                return value, name
        return None, None

    if protocol == "anthropic":
        key_names = (
            "SFORGE_AGENT_API_KEY",
            "ANTHROPIC_AUTH_TOKEN",
            "ANTHROPIC_API_KEY",
        )
        base_names = ("SFORGE_AGENT_API_BASE_URL", "ANTHROPIC_BASE_URL")
    elif protocol == "openai":
        key_names = (
            "SFORGE_AGENT_API_KEY",
            "OPENAI_API_KEY",
            "CODEX_API_KEY",
        )
        base_names = ("SFORGE_AGENT_API_BASE_URL", "OPENAI_BASE_URL")
    elif protocol == "pi-provider":
        return {
            "api_key": None,
            "api_key_source": None,
            "api_base_url": None,
            "api_base_url_source": None,
        }
    else:
        raise ValueError(f"unsupported agent API protocol: {protocol!r}")
    api_key, key_source = first(key_names)
    base_url, base_source = first(base_names)
    return {
        "api_key": api_key,
        "api_key_source": key_source,
        "api_base_url": base_url,
        "api_base_url_source": base_source,
    }


def resolve_pi_auth(env: dict[str, str] | None = None) -> dict[str, Any]:
    source = os.environ if env is None else env
    override = source.get("SFORGE_PI_AUTH_FILE")
    path = (
        Path(override).expanduser()
        if override
        else Path.home() / ".pi" / "agent" / "auth.json"
    )
    valid = False
    if path.is_file():
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            valid = isinstance(payload.get("openai-codex"), dict)
        except (OSError, json.JSONDecodeError, AttributeError):
            valid = False
    return {"path": path, "valid": valid}


def pi_api_key_env_name(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    match = re.fullmatch(
        r"(?:\$\{([A-Z][A-Z0-9_]*)\}|\$([A-Z][A-Z0-9_]*)|([A-Z][A-Z0-9_]*))",
        value,
    )
    if not match:
        return None
    return next(group for group in match.groups() if group is not None)


def resolve_pi_provider(
    model_ref: str,
    env: dict[str, str] | None = None,
) -> dict[str, Any]:
    source = os.environ if env is None else env
    provider, separator, model_id = model_ref.partition("/")
    result: dict[str, Any] = {
        "provider": provider or None,
        "model": model_id or None,
        "models_path": None,
        "model_registered": False,
        "credential_mode": None,
        "credential_env": None,
        "valid": False,
        "error": None,
    }
    if not separator or not provider or not model_id:
        result["error"] = "model must be PROVIDER/MODEL"
        return result
    builtin_keys = {"zai": "ZAI_API_KEY"}
    if provider in builtin_keys:
        key_name = builtin_keys[provider]
        result.update(
            {
                "model_registered": True,
                "credential_mode": "environment",
                "credential_env": key_name,
                "valid": bool(source.get(key_name)),
                "error": None if source.get(key_name) else f"missing {key_name}",
            }
        )
        return result

    models_path = Path(
        source.get(
            "SFORGE_PI_MODELS_FILE",
            Path.home() / ".pi" / "agent" / "models.json",
        )
    ).expanduser().resolve()
    result["models_path"] = str(models_path)
    if not models_path.is_file():
        result["error"] = "Pi models file not found"
        return result
    try:
        models = json.loads(models_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, AttributeError) as exc:
        result["error"] = f"invalid Pi models file: {exc}"
        return result
    provider_config = models.get("providers", {}).get(provider)
    if not isinstance(provider_config, dict):
        result["error"] = f"provider {provider!r} is not registered"
        return result
    registered_ids = {
        entry.get("id")
        for entry in provider_config.get("models", [])
        if isinstance(entry, dict)
    }
    result["model_registered"] = model_id in registered_ids
    if not result["model_registered"]:
        result["error"] = f"model {model_id!r} is not registered"
        return result
    api_key = provider_config.get("apiKey")
    key_name = pi_api_key_env_name(api_key)
    if key_name:
        result.update(
            {
                "credential_mode": "environment",
                "credential_env": key_name,
                "valid": bool(source.get(key_name)),
                "error": None if source.get(key_name) else f"missing {key_name}",
            }
        )
    else:
        result.update(
            {
                "credential_mode": "models-file" if api_key else "none",
                "valid": True,
                "error": None,
            }
        )
    return result


def loopback_api_target(base_url: str) -> tuple[str, int] | None:
    parsed = urllib.parse.urlsplit(base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError(f"invalid agent API base URL: {base_url!r}")
    if parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
        return None
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    return parsed.hostname, port


def bridged_base_url(base_url: str, host: str, port: int) -> str:
    parsed = urllib.parse.urlsplit(base_url)
    netloc = f"[{host}]:{port}" if ":" in host else f"{host}:{port}"
    return urllib.parse.urlunsplit(
        (parsed.scheme, netloc, parsed.path, parsed.query, parsed.fragment)
    )


def default_route_ipv4() -> str:
    route = io.run_capture(["ip", "-j", "-4", "route", "get", "1.1.1.1"])
    if route["returncode"] == 0:
        try:
            payload = json.loads(route["stdout"])
            if payload and payload[0].get("prefsrc"):
                return str(payload[0]["prefsrc"])
        except (json.JSONDecodeError, TypeError, KeyError):
            pass
    raise RuntimeError("could not determine the host default-route IPv4 address")


def reserve_tcp_port(host: str) -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind((host, 0))
        return int(listener.getsockname()[1])


def start_socket_bridge(
    destination: Path,
    *,
    name: str,
    listen_host: str,
    target_host: str,
    target_port: int,
) -> tuple[subprocess.Popen[str], dict[str, Any], Any]:
    paths = current_paths()
    socket_activate = Path("/usr/bin/systemd-socket-activate")
    socket_proxyd = Path("/lib/systemd/systemd-socket-proxyd")
    if not socket_activate.is_file() or not socket_proxyd.is_file():
        raise RuntimeError(
            "rootless Docker loopback bridging requires systemd-socket-activate "
            "and systemd-socket-proxyd"
        )

    listen_port = reserve_tcp_port(listen_host)
    target = (
        f"[{target_host}]:{target_port}"
        if ":" in target_host
        else f"{target_host}:{target_port}"
    )
    command = [
        str(socket_activate),
        f"--listen={listen_host}:{listen_port}",
        str(socket_proxyd),
        target,
    ]
    log_path = destination / "bridges" / f"{name}.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log = log_path.open("a", encoding="utf-8")
    process = subprocess.Popen(
        command,
        cwd=paths.root,
        env=dict(configure_temp_environment(dict(os.environ))),
        stdout=log,
        stderr=subprocess.STDOUT,
        text=True,
        start_new_session=True,
    )
    log.close()
    closed = False

    def close_bridge() -> None:
        nonlocal closed
        if closed:
            return
        closed = True
        if process.poll() is not None:
            return
        try:
            os.killpg(process.pid, signal.SIGTERM)
            process.wait(timeout=5)
        except (ProcessLookupError, subprocess.TimeoutExpired):
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait(timeout=5)

    atexit.register(close_bridge)
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if process.poll() is not None:
            break
        try:
            with socket.create_connection((listen_host, listen_port), timeout=0.25):
                metadata = {
                    "name": name,
                    "listen_host": listen_host,
                    "listen_port": listen_port,
                    "target_host": target_host,
                    "target_port": target_port,
                    "pid": process.pid,
                    "log": io.portable_path(log_path),
                }
                return process, metadata, close_bridge
        except OSError:
            time.sleep(0.1)
    close_bridge()
    raise RuntimeError(
        f"{name} bridge did not become ready; inspect {io.portable_path(log_path)}"
    )


def agent_api_probe_url(base_url: str, protocol: str) -> str:
    base = base_url.rstrip("/")
    if protocol == "anthropic":
        return base + ("/messages" if base.endswith("/v1") else "/v1/messages")
    if protocol == "openai":
        return base + "/models"
    raise ValueError(f"unsupported agent API protocol: {protocol!r}")


def authenticated_api_probe(
    base_url: str,
    api_key: str,
    *,
    protocol: str = "openai",
    model: str | None = None,
    thinking: dict[str, str] | None = None,
    reasoning_effort: str | None = None,
) -> dict[str, Any]:
    url = agent_api_probe_url(base_url, protocol)
    headers = {"Authorization": f"Bearer {api_key}"}
    data: bytes | None = None
    if protocol == "anthropic":
        if not model:
            raise ValueError("Anthropic API probes require a model")
        headers.update(
            {
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            }
        )
        payload: dict[str, Any] = {
            "model": model,
            "max_tokens": 1,
            "messages": [{"role": "user", "content": "Reply OK."}],
        }
        if thinking is not None:
            payload["thinking"] = thinking
        if reasoning_effort is not None:
            payload["reasoning_effort"] = reasoning_effort
        data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(url, headers=headers, data=data)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(request, timeout=10) as response:
            return {"passed": response.status == 200, "status": response.status}
    except urllib.error.HTTPError as exc:
        return {"passed": False, "status": exc.code, "error": str(exc)}
    except (OSError, urllib.error.URLError) as exc:
        return {"passed": False, "status": None, "error": str(exc)}


def append_no_proxy(env: dict[str, str], host: str) -> None:
    current = env.get("NO_PROXY") or env.get("no_proxy") or ""
    entries = [item.strip() for item in current.split(",") if item.strip()]
    if host not in entries:
        entries.insert(0, host)
    value = ",".join(entries)
    env["NO_PROXY"] = value
    env["no_proxy"] = value
    env["SFORGE_NO_PROXY"] = value


def judge_server_environment(
    *,
    api_key: str | None,
    api_base_url: str | None,
    bridge_host: str | None,
    model: str = "gpt-5.5",
) -> dict[str, str]:
    env = dict(os.environ)
    configure_temp_environment(env)
    entries: dict[str, str] = {}
    for item in env.get("SFORGE_JUDGE_EXTRA_ENV", "").split(","):
        if "=" in item:
            key, value = item.split("=", 1)
            entries[key.strip()] = value.strip()
    if api_key:
        entries.setdefault("SFORGE_JUDGE_API_KEY", api_key)
    if api_base_url:
        entries.setdefault("SFORGE_JUDGE_API_BASE_URL", api_base_url)
    entries.setdefault("SFORGE_JUDGE_MODEL", model)
    if entries:
        env["SFORGE_JUDGE_EXTRA_ENV"] = ",".join(
            f"{key}={value}" for key, value in sorted(entries.items())
        )
    if bridge_host:
        append_no_proxy(env, bridge_host)
    return env


def docker_http_probe(
    image: str,
    url: str,
    *,
    api_key: str | None = None,
    protocol: str | None = None,
    model: str | None = None,
    thinking_type: str | None = None,
    reasoning_effort: str | None = None,
) -> dict[str, Any]:
    env = dict(os.environ)
    configure_temp_environment(env)
    env["SFORGE_PROBE_URL"] = agent_api_probe_url(url, protocol) if protocol else url
    command = [
        "docker",
        "run",
        "--rm",
        "--entrypoint",
        "/bin/sh",
        "-e",
        "SFORGE_PROBE_URL",
    ]
    if api_key:
        env["SFORGE_PROBE_API_KEY"] = api_key
        command.extend(["-e", "SFORGE_PROBE_API_KEY"])
    if protocol:
        env["SFORGE_PROBE_PROTOCOL"] = protocol
        command.extend(["-e", "SFORGE_PROBE_PROTOCOL"])
    if model:
        env["SFORGE_PROBE_MODEL"] = model
        command.extend(["-e", "SFORGE_PROBE_MODEL"])
    if thinking_type:
        env["SFORGE_PROBE_THINKING_TYPE"] = thinking_type
        command.extend(["-e", "SFORGE_PROBE_THINKING_TYPE"])
    if reasoning_effort:
        env["SFORGE_PROBE_REASONING_EFFORT"] = reasoning_effort
        command.extend(["-e", "SFORGE_PROBE_REASONING_EFFORT"])
    command.extend(
        [
            image,
            "-c",
            (
                "if [ \"${SFORGE_PROBE_PROTOCOL:-}\" = anthropic ]; then "
                "if [ -n \"${SFORGE_PROBE_REASONING_EFFORT:-}\" ]; then "
                "payload='{\"model\":\"'\"$SFORGE_PROBE_MODEL\"'\","
                "\"max_tokens\":1,\"messages\":[{\"role\":\"user\","
                "\"content\":\"Reply OK.\"}],\"thinking\":{\"type\":\"'"
                "\"$SFORGE_PROBE_THINKING_TYPE\"'\"},\"reasoning_effort\":\"'"
                "\"$SFORGE_PROBE_REASONING_EFFORT\"'\"}'; "
                "else payload='{\"model\":\"'\"$SFORGE_PROBE_MODEL\"'\","
                "\"max_tokens\":1,\"messages\":[{\"role\":\"user\","
                "\"content\":\"Reply OK.\"}],\"thinking\":{\"type\":\"'"
                "\"$SFORGE_PROBE_THINKING_TYPE\"'\"}}'; fi; "
                "auth=\"Authorization: Bearer $SFORGE_PROBE_API_KEY\"; "
                "code=$(curl --noproxy '*' -sS -o /dev/null -w '%{http_code}' "
                "--max-time 30 -X POST -H \"$auth\" "
                "-H 'anthropic-version: 2023-06-01' "
                "-H 'content-type: application/json' "
                "--data \"$payload\" \"$SFORGE_PROBE_URL\"); "
                "elif [ -n \"${SFORGE_PROBE_API_KEY:-}\" ]; then "
                "auth=\"Authorization: Bearer $SFORGE_PROBE_API_KEY\"; "
                "code=$(curl --noproxy '*' -sS -o /dev/null -w '%{http_code}' "
                "--max-time 15 -H \"$auth\" \"$SFORGE_PROBE_URL\"); "
                "else code=$(curl --noproxy '*' -sS -o /dev/null -w '%{http_code}' "
                "--max-time 15 \"$SFORGE_PROBE_URL\"); fi; "
                "printf '%s\\n' \"$code\"; test \"$code\" = 200"
            ),
        ]
    )
    result = io.run_capture(command, env=env)
    return {
        "passed": result["returncode"] == 0,
        "status": result["stdout"].splitlines()[-1] if result["stdout"] else None,
        "stderr": result["stderr"][-400:] or None,
    }


def _docker_memory_bytes(value: str) -> int:
    match = re.fullmatch(r"([0-9]+)([kmgt]?)(?:i?b)?", value.strip().lower())
    if not match:
        raise ValueError(f"unsupported Docker memory limit: {value}")
    amount = int(match.group(1))
    exponent = {"": 0, "k": 1, "m": 2, "g": 3, "t": 4}[match.group(2)]
    return amount * (1024**exponent)


def docker_resource_limit_probe(
    image: str, *, cpu_limit: int, mem_limit: str
) -> dict[str, Any]:
    name = f"edgebench-resource-probe-{os.getpid()}-{time.time_ns()}"
    expected_nano_cpus = int(cpu_limit * 1_000_000_000)
    expected_memory = _docker_memory_bytes(mem_limit)
    started = io.run_capture(
        [
            "docker",
            "run",
            "--detach",
            "--name",
            name,
            "--cpus",
            str(cpu_limit),
            "--memory",
            mem_limit,
            "--entrypoint",
            "/bin/sh",
            image,
            "-c",
            "while :; do sleep 60; done",
        ]
    )
    inspected: dict[str, Any] | None = None
    inspect_result: dict[str, Any] | None = None
    try:
        if started["returncode"] == 0:
            inspect_result = io.run_capture(
                ["docker", "inspect", "--format", "{{json .HostConfig}}", name]
            )
            if inspect_result["returncode"] == 0:
                try:
                    inspected = json.loads(inspect_result["stdout"])
                except json.JSONDecodeError:
                    inspected = None
    finally:
        io.run_capture(["docker", "rm", "--force", name])

    actual_nano_cpus = inspected.get("NanoCpus") if inspected else None
    actual_memory = inspected.get("Memory") if inspected else None
    return {
        "passed": (
            started["returncode"] == 0
            and inspect_result is not None
            and inspect_result["returncode"] == 0
            and actual_nano_cpus == expected_nano_cpus
            and actual_memory == expected_memory
        ),
        "image": image,
        "cpu_limit": cpu_limit,
        "mem_limit": mem_limit,
        "expected_nano_cpus": expected_nano_cpus,
        "actual_nano_cpus": actual_nano_cpus,
        "expected_memory_bytes": expected_memory,
        "actual_memory_bytes": actual_memory,
        "stderr": (
            started["stderr"][-400:]
            or ((inspect_result or {}).get("stderr") or "")[-400:]
            or None
        ),
    }


def sforge_iptables_permission_probe() -> dict[str, Any]:
    python = current_paths().venv_python
    if not python.is_file():
        return {"passed": False, "stderr": "benchmark virtualenv is missing"}
    result = io.run_capture(
        [
            str(python),
            "-c",
            (
                "from sforge.harness.network_isolation import "
                "check_iptables_permission; "
                "raise SystemExit(0 if check_iptables_permission() else 1)"
            ),
        ]
    )
    return {
        "passed": result["returncode"] == 0,
        "stderr": result["stderr"][-400:] or None,
    }


def task_config(task_id: str) -> dict[str, Any]:
    path = current_paths().tasks_dir / f"{task_id}.json"
    if not path.is_file():
        raise FileNotFoundError(
            f"task definition missing: {path}; run provision first"
        )
    return io.read_json(path)


def task_images(task_id: str) -> tuple[str, str]:
    config = task_config(task_id)
    return (
        f"edgebench.work.{task_id}:{config['work']['image_tag']}",
        f"edgebench.judge.{task_id}:{config['judge']['image_tag']}",
    )


def rust_runtime_asset() -> dict[str, str]:
    path = current_paths().edge_root / "sforge" / "harness" / "runtime_assets.json"
    payload = io.read_json(path)
    asset = payload.get("rust") if payload.get("schema_version") == 1 else None
    required = {"version", "target", "archive_name", "url", "sha256"}
    if not isinstance(asset, dict) or required - set(asset):
        raise RuntimeError(f"invalid EdgeBench runtime asset manifest: {path}")
    return {key: str(asset[key]) for key in required}


def rust_runtime_archive_status() -> dict[str, Any]:
    try:
        asset = rust_runtime_asset()
        archive = Path.home() / ".cache" / "sforge" / "rust" / asset["archive_name"]
        actual_sha256 = io.sha256_file(archive) if archive.is_file() else None
        return {
            "passed": actual_sha256 == asset["sha256"],
            "path": str(archive),
            "version": asset["version"],
            "expected_sha256": asset["sha256"],
            "actual_sha256": actual_sha256,
        }
    except (OSError, RuntimeError, json.JSONDecodeError) as exc:
        return {"passed": False, "error": str(exc)}


def rust_image_runtime_probe(image: str, version: str) -> dict[str, Any]:
    command = (
        "set -e; command -v cargo; command -v rustc; "
        f"cargo --version | grep -F 'cargo {version} '; "
        f"rustc --version | grep -F 'rustc {version} '"
    )
    return io.run_capture(
        ["docker", "run", "--rm", "--entrypoint", "/bin/bash", image, "-c", command]
    )


def dataset_revision(task_id: str) -> str | None:
    metadata = (
        current_paths().tasks_dir
        / ".cache"
        / "huggingface"
        / "download"
        / f"{task_id}.json.metadata"
    )
    if not metadata.is_file():
        return None
    lines = metadata.read_text(encoding="utf-8").splitlines()
    return lines[0].strip() if lines else None


def ensure_local_task_exclude() -> None:
    """Keep fetched task data out of managed-source dirty-state checks."""

    exclude = current_paths().edge_root / ".git" / "info" / "exclude"
    if not exclude.is_file():
        return
    lines = exclude.read_text(encoding="utf-8").splitlines()
    if "tasks/" not in lines:
        exclude.write_text("\n".join([*lines, "tasks/"]).rstrip() + "\n", encoding="utf-8")


def provision(profile: dict[str, Any]) -> int:
    paths = current_paths()
    if not paths.sforge.is_file():
        raise FileNotFoundError(
            "SForge is not installed; run repro_env.py bootstrap --only edgebench"
        )
    ensure_local_task_exclude()
    env = dict(os.environ)
    configure_temp_environment(env)
    fetch = [
        str(paths.sforge),
        "--tasks-dir",
        str(paths.tasks_dir),
        "fetch-tasks",
        "--repo",
        str(profile["dataset_repository"]),
        "--revision",
        str(profile["dataset_revision"]),
    ]
    completed = subprocess.run(fetch, cwd=paths.root, env=env, check=False)
    if completed.returncode != 0:
        return completed.returncode
    pull = [
        str(paths.sforge),
        "--tasks-dir",
        str(paths.tasks_dir),
        "pull",
        "--task",
        *[str(task) for task in profile["task_ids"]],
        "--registry",
        str(profile["registry"]),
    ]
    return subprocess.run(pull, cwd=paths.root, env=env, check=False).returncode


class DoctorReport:
    """Ordered, machine-readable collection of environment checks."""

    def __init__(self, profile_id: str) -> None:
        self.profile_id = profile_id
        self.checks: list[dict[str, Any]] = []

    def add(self, name: str, passed: bool, **details: Any) -> None:
        self.checks.append({"name": name, "passed": bool(passed), **details})

    def payload(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "checked_at": io.utc_now(),
            "profile": self.profile_id,
            "ok": all(check["passed"] for check in self.checks),
            "checks": self.checks,
        }


def _check_protocol(
    report: DoctorReport, profile: dict[str, Any]
) -> dict[str, Any] | None:
    try:
        official = load_official_codex_protocol()
        report.add(
            "protocol:official-source",
            True,
            path=official["source"],
            sha256=official["source_sha256"],
            task_count=len(official["tasks"]),
        )
        missing = sorted(set(profile["task_ids"]) - set(official["tasks"]))
        report.add(
            "protocol:task-coverage",
            not missing,
            profile_task_count=len(profile["task_ids"]),
            official_task_count=len(official["tasks"]),
            missing_tasks=missing,
        )
        return official
    except (OSError, ValueError, yaml.YAMLError) as exc:
        report.add(
            "protocol:official-source",
            False,
            path=io.portable_path(current_paths().official_codex_protocol_path),
            error=str(exc),
        )
        return None


def _check_checkouts_and_runtime(report: DoctorReport) -> None:
    paths = current_paths()
    expected_edge = io.upstream_entry("edgebench")["tracking_branch"]
    expected_goal = io.upstream_entry("goal_plus")["tracking_branch"]
    edge_branch = io.git_branch(paths.edge_root)
    edge_dirty = io.git_dirty(paths.edge_root)
    goal_branch = io.git_branch(paths.goal_plus_root)
    goal_dirty = io.git_dirty(paths.goal_plus_root)
    report.add(
        "checkout:edgebench",
        edge_branch == expected_edge and edge_dirty is False,
        expected_branch=expected_edge,
        actual_branch=edge_branch,
        actual_commit=io.git_head(paths.edge_root),
        dirty=edge_dirty,
    )
    report.add(
        "checkout:goal-plus",
        goal_branch == expected_goal and goal_dirty is False,
        expected_branch=expected_goal,
        actual_branch=goal_branch,
        actual_commit=io.git_head(paths.goal_plus_root),
        dirty=goal_dirty,
    )
    report.add(
        "entrypoint:sforge",
        paths.sforge.is_file(),
        path=".bench-env/venv/bin/sforge",
    )
    imports = (
        io.run_capture([str(paths.venv_python), "-c", "import fastapi, sforge"])
        if paths.venv_python.is_file()
        else {"returncode": 127, "stderr": "venv missing"}
    )
    report.add(
        "runtime:sforge-server-dependencies",
        imports["returncode"] == 0,
        stderr=imports["stderr"][-400:] or None,
    )
    report.add(
        "runtime:repository-local-temp", ensure_temp_root().is_dir(), path=".tmp"
    )


def _check_auth(
    report: DoctorReport, profile: dict[str, Any]
) -> tuple[str, dict[str, str | None]]:
    api_protocol = api_protocol_for_methods(profile["methods"])
    agents = {str(METHODS[method]["agent"]) for method in profile["methods"]}
    api_config = resolve_agent_api_config(protocol=api_protocol)
    auth_override = os.environ.get("SFORGE_CODEX_AUTH_FILE")
    codex_home = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))
    auth = Path(auth_override).expanduser() if auth_override else codex_home / "auth.json"
    pi_auth_status = resolve_pi_auth()
    pi_provider_status = (
        resolve_pi_provider(str(profile["model"]))
        if api_protocol == "pi-provider"
        else None
    )
    api_key = api_config["api_key"]
    api_base_url = api_config["api_base_url"]
    needs_codex = any(agent.startswith("codex") for agent in agents)
    needs_pi = any(agent.startswith("pi") for agent in agents)
    needs_pi_oauth = needs_pi and api_protocol != "pi-provider"
    needs_claude = "claude-code" in agents
    auth_ready = (
        (not needs_codex or bool(api_key) or auth.is_file())
        and (not needs_pi_oauth or bool(pi_auth_status["valid"]))
        and (pi_provider_status is None or bool(pi_provider_status["valid"]))
        and (not needs_claude or bool(api_key))
    )
    report.add(
        "auth:agent",
        auth_ready,
        mode=(
            "pi-provider"
            if pi_provider_status is not None
            else "api_key"
            if api_key
            else "host_login"
        ),
        protocol=api_protocol,
        api_key_source=api_config["api_key_source"],
        api_base_url_source=api_config["api_base_url_source"],
        policy=(
            "Codex accepts API credentials or Codex auth; openai-codex Pi requires "
            "a Pi auth file; pi-provider uses the explicit provider/model registry"
        ),
    )
    if needs_codex:
        report.add(
            "auth:codex",
            bool(api_key) or auth.is_file(),
            mode="api_key" if api_key else "oauth",
            path=str(auth),
        )
    if needs_pi:
        if pi_provider_status is not None:
            report.add(
                "auth:pi",
                bool(pi_provider_status["valid"]),
                mode="provider-api",
                provider=pi_provider_status["provider"],
                model=pi_provider_status["model"],
                models_path=pi_provider_status["models_path"],
                model_registered=pi_provider_status["model_registered"],
                credential_mode=pi_provider_status["credential_mode"],
                credential_env=pi_provider_status["credential_env"],
                error=pi_provider_status["error"],
            )
        else:
            report.add(
                "auth:pi",
                bool(pi_auth_status["valid"]),
                mode="openai-codex",
                path=str(pi_auth_status["path"]),
            )
    if api_key and api_base_url:
        api_probe = authenticated_api_probe(
            str(api_base_url),
            str(api_key),
            protocol=api_protocol,
            model=str(profile["model"]),
            thinking=profile.get("thinking"),
            reasoning_effort=profile.get("reasoning_effort"),
        )
        report.add(
            "auth:agent-api-host",
            bool(api_probe["passed"]),
            base_url=str(api_base_url),
            status=api_probe.get("status"),
            error=api_probe.get("error"),
        )
        try:
            loopback = loopback_api_target(str(api_base_url)) is not None
        except ValueError as exc:
            loopback = False
            report.add("auth:agent-api-url", False, error=str(exc))
        if loopback:
            report.add(
                "runtime:rootless-loopback-bridge",
                Path("/usr/bin/systemd-socket-activate").is_file()
                and Path("/lib/systemd/systemd-socket-proxyd").is_file(),
                mechanism="systemd-socket-proxyd",
            )
    if needs_codex:
        codex_runtime = (
            Path.home()
            / ".cache"
            / "sforge"
            / "codex"
            / "codex-0.144.1-linux-x64.tgz"
        )
        report.add(
            "runtime:codex-host-cache",
            codex_runtime.is_file() and codex_runtime.stat().st_size > 0,
            path=str(codex_runtime),
            size=codex_runtime.stat().st_size if codex_runtime.is_file() else None,
        )
    return api_protocol, api_config


def _docker_details(report: DoctorReport) -> dict[str, Any]:
    docker_info = io.run_capture(["docker", "info", "--format", "{{json .}}"])
    details: dict[str, Any] = {}
    if docker_info["returncode"] == 0:
        try:
            details = json.loads(docker_info["stdout"])
        except json.JSONDecodeError:
            details = {}
    architecture = str(details.get("Architecture") or "").lower()
    report.add(
        "docker:engine",
        docker_info["returncode"] == 0 and bool(details),
        architecture=architecture or None,
        stderr=docker_info["stderr"][-400:] or None,
    )
    report.add(
        "docker:linux-amd64",
        architecture in {"amd64", "x86_64"},
        required="linux/amd64",
        actual=architecture or None,
    )
    return details


def _check_tasks_and_resources(
    report: DoctorReport,
    profile: dict[str, Any],
    official_protocol: dict[str, Any] | None,
    docker_details: dict[str, Any],
) -> None:
    paths = current_paths()
    rust_archive: dict[str, Any] | None = None
    resource_probe_image: str | None = None
    effective_protocols: list[dict[str, Any]] = []
    offline_task_ids: list[str] = []
    for task_id in profile["task_ids"]:
        task_path = paths.tasks_dir / f"{task_id}.json"
        report.add(
            f"task:{task_id}", task_path.is_file(), path=io.portable_path(task_path)
        )
        actual_revision = dataset_revision(task_id)
        report.add(
            f"dataset-revision:{task_id}",
            actual_revision == profile["dataset_revision"],
            expected=profile["dataset_revision"],
            actual=actual_revision,
        )
        if not task_path.is_file():
            continue
        config = task_config(task_id)
        if official_protocol is not None:
            try:
                effective = profile_task_protocol(
                    profile, official_protocol, task_id, config
                )
                effective_protocols.append(effective)
                if effective["internet"] is False:
                    offline_task_ids.append(task_id)
                report.add(
                    f"protocol-effective:{task_id}",
                    True,
                    internet=effective["internet"],
                    internet_source=(
                        f"profiles/{profile['id']}.protocol_overrides.internet"
                        if "internet" in profile.get("protocol_overrides", {})
                        else f"tasks/{task_id}.json"
                    ),
                    submission_cooldown=effective["submission_cooldown"],
                )
            except ValueError as exc:
                report.add(f"protocol-effective:{task_id}", False, error=str(exc))
        if config.get("base_image") == "rust" and rust_archive is None:
            rust_archive = rust_runtime_archive_status()
            report.add(
                "runtime:rust-host-cache",
                bool(rust_archive["passed"]),
                **{key: value for key, value in rust_archive.items() if key != "passed"},
            )
        for image_index, image in enumerate(task_images(task_id)):
            inspected = io.run_capture(["docker", "image", "inspect", image])
            report.add(
                f"image:{image}", inspected["returncode"] == 0, image=image
            )
            if (
                image_index == 0
                and inspected["returncode"] == 0
                and resource_probe_image is None
            ):
                resource_probe_image = image
            if config.get("base_image") == "rust" and inspected["returncode"] == 0:
                assert rust_archive is not None
                version = str(rust_archive.get("version") or "")
                probe = (
                    rust_image_runtime_probe(image, version)
                    if version
                    else {
                        "returncode": 1,
                        "stdout": "",
                        "stderr": "Rust runtime manifest has no version",
                    }
                )
                native = probe["returncode"] == 0
                report.add(
                    f"runtime:rust:{image}",
                    native or bool(rust_archive["passed"]),
                    image=image,
                    expected_version=version,
                    native=native,
                    fallback_archive_ready=bool(rust_archive["passed"]),
                    stdout=probe["stdout"][-400:] or None,
                    stderr=probe["stderr"][-400:] or None,
                )

    if effective_protocols:
        work_cpu_limit = max(
            max(int(item["work_cpu_limit"]), int(item["judge_cpu_limit"]))
            for item in effective_protocols
        )
        work_mem_limit = max(
            (
                str(limit)
                for item in effective_protocols
                for limit in (item["work_mem_limit"], item["judge_mem_limit"])
            ),
            key=_docker_memory_bytes,
        )
        resource_probe = (
            docker_resource_limit_probe(
                resource_probe_image,
                cpu_limit=work_cpu_limit,
                mem_limit=work_mem_limit,
            )
            if resource_probe_image
            else {
                "passed": False,
                "error": "no prepared Work image is available for the resource probe",
            }
        )
        daemon_cpu_support = docker_details.get("CpuCfsQuota")
        daemon_memory_support = docker_details.get("MemoryLimit")
        report.add(
            "docker:official-resource-limits",
            daemon_cpu_support is not False
            and daemon_memory_support is not False
            and bool(resource_probe["passed"]),
            daemon_cpu_cfs_quota=daemon_cpu_support,
            daemon_memory_limit=daemon_memory_support,
            **{key: value for key, value in resource_probe.items() if key != "passed"},
        )
    if offline_task_ids:
        isolation_probe = sforge_iptables_permission_probe()
        report.add(
            "network:offline-task-isolation",
            bool(isolation_probe["passed"]),
            mechanism="SForge passwordless sudo iptables allowlist",
            offline_task_count=len(offline_task_ids),
            sample_task=offline_task_ids[0],
            stderr=isolation_probe.get("stderr"),
        )


def doctor_payload(profile: dict[str, Any]) -> dict[str, Any]:
    report = DoctorReport(str(profile["id"]))
    official_protocol = _check_protocol(report, profile)
    _check_checkouts_and_runtime(report)
    _check_auth(report, profile)
    docker_details = _docker_details(report)
    _check_tasks_and_resources(report, profile, official_protocol, docker_details)
    return report.payload()


def doctor(profile: dict[str, Any], *, output: Path | None = None) -> int:
    payload = doctor_payload(profile)
    if output:
        io.write_json(output, payload)
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0 if payload["ok"] else 1

"""Repository-local lifecycle for exposing host loopback services to Docker."""

from __future__ import annotations

import atexit
import json
import os
import signal
import socket
import subprocess
import time
import urllib.parse
from pathlib import Path
from typing import Any, Callable

from bench_runtime_paths import configure_temp_environment


def loopback_target(base_url: str) -> tuple[str, int] | None:
    parsed = urllib.parse.urlsplit(base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError(f"invalid agent API base URL: {base_url!r}")
    if parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
        return None
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    return parsed.hostname, port


def bridged_url(base_url: str, host: str, port: int) -> str:
    parsed = urllib.parse.urlsplit(base_url)
    netloc = f"[{host}]:{port}" if ":" in host else f"{host}:{port}"
    return urllib.parse.urlunsplit(
        (parsed.scheme, netloc, parsed.path, parsed.query, parsed.fragment)
    )


def default_route_ipv4(*, root: Path) -> str:
    completed = subprocess.run(
        ["ip", "-j", "-4", "route", "get", "1.1.1.1"],
        cwd=root,
        env=dict(configure_temp_environment(dict(os.environ))),
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode == 0:
        try:
            payload = json.loads(completed.stdout)
            if payload and payload[0].get("prefsrc"):
                return str(payload[0]["prefsrc"])
        except (json.JSONDecodeError, TypeError, KeyError):
            pass
    raise RuntimeError("could not determine the host default-route IPv4 address")


def _reserve_tcp_port(host: str) -> int:
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
    root: Path,
    display_path: Callable[[Path], str] = str,
) -> tuple[subprocess.Popen[str], dict[str, Any], Callable[[], None]]:
    socket_activate = Path("/usr/bin/systemd-socket-activate")
    socket_proxyd = Path("/lib/systemd/systemd-socket-proxyd")
    if not socket_activate.is_file() or not socket_proxyd.is_file():
        raise RuntimeError(
            "rootless Docker loopback bridging requires systemd-socket-activate "
            "and systemd-socket-proxyd"
        )

    listen_port = _reserve_tcp_port(listen_host)
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
    with log_path.open("a", encoding="utf-8") as log:
        process = subprocess.Popen(
            command,
            cwd=root,
            env=dict(configure_temp_environment(dict(os.environ))),
            stdout=log,
            stderr=subprocess.STDOUT,
            text=True,
            start_new_session=True,
        )
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
                    "log": display_path(log_path),
                }
                return process, metadata, close_bridge
        except OSError:
            time.sleep(0.1)
    close_bridge()
    raise RuntimeError(
        f"{name} bridge did not become ready; inspect {display_path(log_path)}"
    )

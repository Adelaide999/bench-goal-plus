"""Read-only inventory and full host/runtime doctor for SWE-bench Verified."""

from __future__ import annotations

import importlib.metadata
import json
import os
import shutil
import subprocess
import urllib.error
import urllib.request
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from bench_goal_plus.loopback_bridge import (
    bridged_url,
    default_route_ipv4,
    loopback_target,
    start_socket_bridge,
)
from bench_runtime_paths import (
    configure_temp_environment,
    temporary_directory,
)

from .config import ROOT, SWEBENCH_ROOT, SweBenchContractError, utc_now, write_json


CODEX_ARCHIVE = Path.home() / ".cache/sforge/codex/codex-0.144.1-linux-x64.tgz"
CODEX_RUNTIME_TMPFS = "/opt/codex:rw,exec,nosuid,nodev,size=512m"
PI_API_KEYS = {
    "zai": ("ZAI_API_KEY", "ZAI_CODING_CN_API_KEY"),
    "deepseek": ("DEEPSEEK_API_KEY",),
    "openai": ("OPENAI_API_KEY",),
    "anthropic": ("ANTHROPIC_OAUTH_TOKEN", "ANTHROPIC_API_KEY"),
}


def run_capture(
    command: list[str],
    *,
    timeout: int = 60,
    environment: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=timeout,
    )


def image_inventory(profile: dict[str, Any]) -> dict[str, Any]:
    images: list[dict[str, Any]] = []
    for task in profile["tasks"]:
        reference = task["image"]
        inspected = run_capture(["docker", "image", "inspect", reference])
        entry: dict[str, Any] = {
            "task_id": task["instance_id"],
            "reference": reference,
            "present": inspected.returncode == 0,
        }
        if inspected.returncode == 0:
            try:
                values = json.loads(inspected.stdout)
                value = values[0]
                entry.update(
                    {
                        "image_id": value.get("Id"),
                        "repo_tags": value.get("RepoTags") or [],
                        "repo_digests": value.get("RepoDigests") or [],
                        "size_bytes": value.get("Size"),
                        "architecture": value.get("Architecture"),
                        "os": value.get("Os"),
                    }
                )
            except (json.JSONDecodeError, IndexError, TypeError):
                entry["inspect_error"] = "docker image inspect returned invalid JSON"
        else:
            entry["inspect_error"] = inspected.stderr.strip() or inspected.stdout.strip()
        images.append(entry)

    containers_result = run_capture(
        [
            "docker",
            "ps",
            "-a",
            "--no-trunc",
            "--format",
            "{{json .}}",
        ]
    )
    containers: list[dict[str, Any]] = []
    if containers_result.returncode == 0:
        for line in containers_result.stdout.splitlines():
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                containers.append(value)
    for image in images:
        reference = image["reference"]
        image_id = str(image.get("image_id") or "")
        image["associated_containers"] = [
            {
                "id": item.get("ID"),
                "name": item.get("Names"),
                "state": item.get("State"),
                "status": item.get("Status"),
            }
            for item in containers
            if item.get("Image") == reference
            or (image_id and str(item.get("Image", "")).startswith(image_id))
        ]

    return {
        "schema_version": 1,
        "benchmark_id": "swe-bench-verified",
        "profile": profile["id"],
        "dataset": {
            "name": profile["dataset"]["name"],
            "split": profile["dataset"]["split"],
            "revision": profile["dataset"]["revision"],
            "task_ids": profile["task_ids"],
            "metadata_source": "pinned profile",
        },
        "images": images,
        "docker_ps_ok": containers_result.returncode == 0,
        "read_only": True,
        "acquisition_attempted": False,
        "ok": bool(
            containers_result.returncode == 0
            and all(
                item.get("present")
                and item.get("architecture") == "amd64"
                and item.get("os") == "linux"
                for item in images
            )
        ),
        "checked_at": utc_now(),
    }


def _check(name: str, passed: bool, **details: Any) -> dict[str, Any]:
    return {"name": name, "passed": bool(passed), **details}


def _git_value(*args: str) -> str | None:
    result = run_capture(["git", "-C", str(SWEBENCH_ROOT), *args])
    return result.stdout.strip() if result.returncode == 0 else None


def _package_version(name: str) -> str | None:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return None


def resolve_codex_runtime(profile: dict[str, Any]) -> dict[str, Any]:
    archive = Path(os.environ.get("SWEBENCH_CODEX_RUNTIME_ARCHIVE", CODEX_ARCHIVE))
    provider = profile["agent_provider"]
    base_url_env = str(provider["base_url_env"])
    api_key_env = str(provider["api_key_env"])
    return {
        "archive": archive,
        "archive_present": archive.is_file(),
        "provider_id": str(provider["id"]),
        "provider_name": str(provider["name"]),
        "auth_mode": str(provider["auth_mode"]),
        "wire_api": str(provider["wire_api"]),
        "base_url_env": base_url_env,
        "api_key_env": api_key_env,
        "api_base_url": os.environ.get(base_url_env),
        "credential_present": bool(os.environ.get(api_key_env)),
    }


def _safe_response_facts(
    status: int | None, payload: Any, *, expected_model: str
) -> dict[str, Any]:
    body = payload if isinstance(payload, dict) else {}
    result = {
        "passed": bool(
            status is not None
            and 200 <= status < 300
            and body.get("object") == "response"
            and body.get("model") == expected_model
            and body.get("status") == "completed"
        ),
        "http_status": status,
        "object": body.get("object"),
        "model": body.get("model"),
        "response_status": body.get("status"),
    }
    error = body.get("error")
    if isinstance(error, dict):
        result["error_type"] = error.get("type")
        result["error_code"] = error.get("code")
    return result


def openai_responses_probe(
    base_url: str, *, api_key_env: str, model: str, timeout: float = 45.0
) -> dict[str, Any]:
    api_key = os.environ.get(api_key_env)
    if not api_key:
        return {
            "passed": False,
            "http_status": None,
            "error": f"missing credential environment variable: {api_key_env}",
        }
    payload = json.dumps(
        {
            "model": model,
            "input": "Reply with exactly WIRE_OK.",
            "max_output_tokens": 16,
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        base_url.rstrip("/") + "/responses",
        data=payload,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
    )
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(request, timeout=timeout) as response:
            decoded = json.loads(response.read().decode("utf-8"))
            return _safe_response_facts(
                response.status, decoded, expected_model=model
            )
    except urllib.error.HTTPError as error:
        try:
            decoded = json.loads(error.read().decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            decoded = None
        return _safe_response_facts(error.code, decoded, expected_model=model)
    except (OSError, urllib.error.URLError, json.JSONDecodeError) as error:
        return {"passed": False, "http_status": None, "error": str(error)}


@contextmanager
def routed_codex_runtime(
    profile: dict[str, Any], destination: Path
) -> Iterator[dict[str, Any]]:
    runtime = resolve_codex_runtime(profile)
    if not runtime["api_base_url"] or not runtime["credential_present"]:
        raise SweBenchContractError(
            "Plain Codex requires the profile-selected OpenAI-compatible base URL and key"
        )
    runtime["runtime_api_base_url"] = str(runtime["api_base_url"])
    runtime["bridge_host"] = None
    runtime["bridge"] = None
    closer = None
    try:
        target = loopback_target(str(runtime["api_base_url"]))
        if target is not None:
            bridge_host = default_route_ipv4(root=ROOT)
            _, metadata, closer = start_socket_bridge(
                destination,
                name="agent-api",
                listen_host=bridge_host,
                target_host=target[0],
                target_port=target[1],
                root=ROOT,
                display_path=lambda path: str(path.relative_to(ROOT)),
            )
            runtime["bridge_host"] = bridge_host
            runtime["bridge"] = metadata
            runtime["runtime_api_base_url"] = bridged_url(
                str(runtime["api_base_url"]),
                bridge_host,
                int(metadata["listen_port"]),
            )
        yield runtime
    finally:
        if closer is not None:
            closer()


def resolve_pi_runtime(model: str) -> dict[str, Any]:
    node_command = shutil.which("node")
    pi_command = shutil.which("pi")
    node_binary = Path(node_command).resolve() if node_command else None
    pi_cli = Path(pi_command).resolve() if pi_command else None
    node_root = node_binary.parent.parent if node_binary else None
    package_root = pi_cli.parent.parent if pi_cli else None
    provider, _, model_id = model.partition("/")
    key_names = PI_API_KEYS.get(provider, ())
    key_source = next((name for name in key_names if os.environ.get(name)), None)
    return {
        "node_root": node_root,
        "node_binary": node_binary,
        "package_root": package_root,
        "pi_cli": pi_cli,
        "provider": provider,
        "model_id": model_id,
        "credential_env": key_source,
        "credential_present": key_source is not None,
    }


def _codex_container_probe(image: str, archive: Path) -> subprocess.CompletedProcess[str]:
    return run_capture(
        [
            "docker",
            "run",
            "--pull",
            "never",
            "--rm",
            "--tmpfs",
            CODEX_RUNTIME_TMPFS,
            "--mount",
            f"type=bind,src={archive},dst=/opt/runtime/codex.tgz,readonly",
            image,
            "sh",
            "-lc",
            "mkdir -p /opt/codex && tar -xzf /opt/runtime/codex.tgz -C /opt/codex && "
            "/opt/codex/package/vendor/x86_64-unknown-linux-musl/bin/codex --version",
        ],
        timeout=120,
    )


_CONTAINER_RESPONSES_PROBE = """
import json
import os
import urllib.error
import urllib.request

model = os.environ["SWEBENCH_API_MODEL"]
key = os.environ[os.environ["SWEBENCH_API_KEY_ENV"]]
payload = json.dumps({
    "model": model,
    "input": "Reply with exactly WIRE_OK.",
    "max_output_tokens": 16,
}).encode("utf-8")
request = urllib.request.Request(
    os.environ["SWEBENCH_API_BASE_URL"].rstrip("/") + "/responses",
    data=payload,
    headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"},
)
result = {"passed": False, "http_status": None}
try:
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(request, timeout=45) as response:
        body = json.loads(response.read().decode("utf-8"))
        result.update({
            "http_status": response.status,
            "object": body.get("object"),
            "model": body.get("model"),
            "response_status": body.get("status"),
        })
        result["passed"] = bool(
            200 <= response.status < 300
            and body.get("object") == "response"
            and body.get("model") == model
            and body.get("status") == "completed"
        )
except urllib.error.HTTPError as error:
    result["http_status"] = error.code
except Exception as error:
    result["error"] = type(error).__name__ + ": " + str(error)
print(json.dumps(result, sort_keys=True))
raise SystemExit(0 if result["passed"] else 1)
""".strip()


def codex_container_responses_probe(
    target: str,
    runtime: dict[str, Any],
    *,
    model: str,
    existing_container: bool = False,
) -> dict[str, Any]:
    environment = dict(configure_temp_environment(dict(os.environ)))
    environment.update(
        {
            "SWEBENCH_API_BASE_URL": str(runtime["runtime_api_base_url"]),
            "SWEBENCH_API_KEY_ENV": str(runtime["api_key_env"]),
            "SWEBENCH_API_MODEL": model,
        }
    )
    inherited_names = [
        str(runtime["api_key_env"]),
        "SWEBENCH_API_BASE_URL",
        "SWEBENCH_API_KEY_ENV",
        "SWEBENCH_API_MODEL",
    ]
    if existing_container:
        command = ["docker", "exec"]
        for name in inherited_names:
            command.extend(["-e", name])
        command.extend([target, "python", "-c", _CONTAINER_RESPONSES_PROBE])
    else:
        command = [
            "docker",
            "run",
            "--pull",
            "never",
            "--rm",
            "--entrypoint",
            "python",
        ]
        for name in inherited_names:
            command.extend(["-e", name])
        command.extend([target, "-c", _CONTAINER_RESPONSES_PROBE])
    completed = run_capture(command, timeout=90, environment=environment)
    try:
        payload = json.loads(completed.stdout.splitlines()[-1])
    except (json.JSONDecodeError, IndexError):
        payload = {"passed": False, "http_status": None}
    payload["passed"] = completed.returncode == 0 and payload.get("passed") is True
    if completed.stderr:
        payload["stderr"] = completed.stderr.strip()[-400:]
    return payload


def _image_checkout_probe(
    image: str, base_commit: str
) -> subprocess.CompletedProcess[str]:
    return run_capture(
        [
            "docker",
            "run",
            "--pull",
            "never",
            "--rm",
            "--entrypoint",
            "git",
            image,
            "-C",
            "/testbed",
            "rev-parse",
            "HEAD",
            f"{base_commit}^{{tree}}",
            "HEAD^{tree}",
        ],
        timeout=120,
    )


def _pi_container_probe(
    image: str, runtime: dict[str, Any]
) -> subprocess.CompletedProcess[str]:
    provider = str(runtime["provider"])
    credential_env = str(runtime["credential_env"])
    return run_capture(
        [
            "docker",
            "run",
            "--pull",
            "never",
            "--rm",
            "-e",
            credential_env,
            "--mount",
            f"type=bind,src={runtime['node_root']},dst=/opt/node,readonly",
            "--mount",
            f"type=bind,src={runtime['package_root']},dst=/opt/pi,readonly",
            image,
            "/opt/node/bin/node",
            "/opt/pi/dist/cli.js",
            "--offline",
            "--list-models",
            provider,
        ],
        timeout=120,
    )


def doctor_payload(profile: dict[str, Any]) -> dict[str, Any]:
    inventory = image_inventory(profile)
    checks: list[dict[str, Any]] = [
        _check("inventory:exact-images", inventory["ok"]),
    ]
    docker_info = run_capture(["docker", "info", "--format", "{{json .}}"])
    docker_architecture = None
    if docker_info.returncode == 0:
        try:
            docker_architecture = json.loads(docker_info.stdout).get("Architecture")
        except (json.JSONDecodeError, AttributeError):
            docker_architecture = None
    checks.append(
        _check(
            "docker:linux-amd64",
            docker_info.returncode == 0 and docker_architecture == "x86_64",
            architecture=docker_architecture,
        )
    )

    branch = _git_value("branch", "--show-current")
    head = _git_value("rev-parse", "HEAD")
    upstream = _git_value("rev-parse", "--abbrev-ref", "@{upstream}")
    dirty = _git_value("status", "--porcelain")
    checks.append(
        _check(
            "checkout:swebench",
            bool(
                SWEBENCH_ROOT.is_dir()
                and branch == "main"
                and upstream == "origin/main"
                and head
                and dirty == ""
            ),
            path=str(SWEBENCH_ROOT),
            branch=branch,
            upstream=upstream,
            commit=head,
            dirty=dirty not in (None, ""),
        )
    )
    package_versions = {
        name: _package_version(name)
        for name in ("swebench", "datasets", "unidiff", "docker")
    }
    for name, version in package_versions.items():
        checks.append(
            _check(f"package:{name}", version is not None, version=version)
        )

    method = profile["methods"][0]
    image = profile["tasks"][0]["image"]
    base_commit = profile["tasks"][0]["base_commit"]
    checkout_probe = _image_checkout_probe(image, base_commit)
    checkout_values = checkout_probe.stdout.splitlines()
    checkout_valid = (
        checkout_probe.returncode == 0
        and len(checkout_values) == 3
        and checkout_values[1] == checkout_values[2]
    )
    checks.append(
        _check(
            "image:dataset-base-tree",
            checkout_valid,
            base_commit=base_commit,
            observed_head=checkout_values[0] if checkout_values else None,
            base_tree=(checkout_values[1] if len(checkout_values) > 1 else None),
            observed_tree=(checkout_values[2] if len(checkout_values) > 2 else None),
            error=checkout_probe.stderr.strip()[-2000:],
        )
    )
    runtime: dict[str, Any]
    if method == "plain-codex":
        runtime = resolve_codex_runtime(profile)
        api_config_valid = bool(
            runtime["auth_mode"] == "openai-compatible"
            and runtime["wire_api"] == "responses"
            and runtime["api_base_url"]
            and runtime["credential_present"]
        )
        checks.extend(
            [
                _check(
                    "codex:runtime-archive",
                    runtime["archive_present"],
                    path=str(runtime["archive"]),
                ),
                _check(
                    "codex:openai-compatible-config",
                    api_config_valid,
                    provider=runtime["provider_id"],
                    auth_mode=runtime["auth_mode"],
                    wire_api=runtime["wire_api"],
                    base_url_env=runtime["base_url_env"],
                    api_key_env=runtime["api_key_env"],
                    base_url=runtime["api_base_url"],
                ),
            ]
        )
        if runtime["archive_present"]:
            probe = _codex_container_probe(image, runtime["archive"])
            checks.append(
                _check(
                    "codex:container-runtime",
                    probe.returncode == 0,
                    version=(probe.stdout or probe.stderr).strip(),
                )
            )
        if api_config_valid:
            host_probe = openai_responses_probe(
                str(runtime["api_base_url"]),
                api_key_env=str(runtime["api_key_env"]),
                model=str(profile["model"]),
            )
            checks.append(
                _check(
                    "codex:host-responses",
                    bool(host_probe["passed"]),
                    **{key: value for key, value in host_probe.items() if key != "passed"},
                )
            )
            route_recorded = False
            container_recorded = False
            try:
                with temporary_directory(
                    prefix="codex-api-doctor-",
                    namespace="swe-bench-verified",
                ) as destination:
                    with routed_codex_runtime(profile, destination) as routed:
                        route_recorded = True
                        checks.append(
                            _check(
                                "codex:container-api-route",
                                True,
                                loopback_bridge=routed["bridge"] is not None,
                                bridge=(
                                    {
                                        key: value
                                        for key, value in routed["bridge"].items()
                                        if key != "pid"
                                    }
                                    if routed["bridge"]
                                    else None
                                ),
                                runtime_base_url=routed["runtime_api_base_url"],
                            )
                        )
                        container_probe = codex_container_responses_probe(
                            image,
                            routed,
                            model=str(profile["model"]),
                        )
                        container_recorded = True
                        checks.append(
                            _check(
                                "codex:container-responses",
                                bool(container_probe["passed"]),
                                **{
                                    key: value
                                    for key, value in container_probe.items()
                                    if key != "passed"
                                },
                            )
                        )
            except Exception as error:
                if not route_recorded:
                    checks.append(
                        _check(
                            "codex:container-api-route",
                            False,
                            error=f"{type(error).__name__}: {error}",
                        )
                    )
                if not container_recorded:
                    checks.append(
                        _check(
                            "codex:container-responses",
                            False,
                            error=f"{type(error).__name__}: {error}",
                        )
                    )
    else:
        runtime = resolve_pi_runtime(profile["model"])
        paths_present = all(
            isinstance(runtime.get(name), Path) and runtime[name].exists()
            for name in ("node_root", "package_root", "pi_cli")
        )
        checks.extend(
            [
                _check(
                    "pi:host-runtime",
                    paths_present,
                    node_root=str(runtime.get("node_root") or ""),
                    package_root=str(runtime.get("package_root") or ""),
                ),
                _check(
                    "pi:credential",
                    runtime["credential_present"],
                    provider=runtime["provider"],
                    credential_env=runtime["credential_env"],
                ),
            ]
        )
        if paths_present and runtime["credential_present"]:
            probe = _pi_container_probe(image, runtime)
            checks.append(
                _check(
                    "pi:container-model",
                    probe.returncode == 0
                    and str(runtime["model_id"]) in probe.stdout,
                    provider=runtime["provider"],
                    model=runtime["model_id"],
                    output=probe.stdout.strip()[-2000:],
                    error=probe.stderr.strip()[-2000:],
                )
            )

    return {
        "schema_version": 1,
        "benchmark_id": "swe-bench-verified",
        "profile": profile["id"],
        "method": method,
        "model": profile["model"],
        "ok": all(item["passed"] for item in checks),
        "checks": checks,
        "inventory": inventory,
        "packages": package_versions,
        "swebench_commit": head,
        "checked_at": utc_now(),
    }


def doctor(
    profile: dict[str, Any],
    *,
    output: Path | None,
    local_assets_only: bool,
    allow_missing_local_assets: bool,
) -> int:
    payload = (
        image_inventory(profile)
        if local_assets_only
        else doctor_payload(profile)
    )
    if output is not None:
        write_json(output, payload)
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    if payload["ok"] or (local_assets_only and allow_missing_local_assets):
        return 0
    return 1

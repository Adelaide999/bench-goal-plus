"""Run-local Goal Plus installation through the plugin's public installer."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess


def installation_environment(run_dir: Path) -> dict[str, str]:
    return {
        "GOAL_PLUS_INSTALL_HOME": str(run_dir / "controller-runtime/goal-plus-install"),
        "CODEX_HOME": str(run_dir / "controller-runtime/codex-home"),
        "PI_CODING_AGENT_DIR": str(run_dir / "pi-home"),
    }


def install_goal_plus(source: Path, workspace: Path, agent_harness: str) -> None:
    if agent_harness not in {"codex", "pi"}:
        raise ValueError(f"unsupported Agent harness: {agent_harness}")
    run_dir = workspace.parent
    environment = {**os.environ, **installation_environment(run_dir)}
    installer = str(source / "install.sh")
    with (run_dir / "goal-plus-install.log").open("w") as output:
        subprocess.run(
            [installer, f"--{agent_harness}", "--yes"], cwd=workspace,
            env=environment, stdout=output, stderr=subprocess.STDOUT, check=True,
        )
    result = subprocess.run(
        [installer, "--runtime-info"], cwd=workspace, env=environment,
        capture_output=True, text=True, check=True,
    )
    receipt = json.loads(result.stdout)
    if not Path(receipt["python"]).is_file() or not Path(receipt["package"]).is_dir():
        raise RuntimeError("Goal Plus installer returned an incomplete runtime")
    (run_dir / "goal-plus-runtime.json").write_text(json.dumps(receipt, indent=2) + "\n")


def bind_goal_plus_environment(environment: dict[str, str], run_dir: Path) -> None:
    receipt = json.loads((run_dir / "goal-plus-runtime.json").read_text())
    environment.update(installation_environment(run_dir))
    environment["GOAL_PLUS_PYTHON"] = receipt["python"]
    environment["PATH"] = str(Path(receipt["python"]).parent) + os.pathsep + environment["PATH"]

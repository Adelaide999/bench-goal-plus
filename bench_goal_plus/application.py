"""Application service behind the repository's benchmark Agent Skills."""

from __future__ import annotations

import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

from adapters.registry import load_adapter

from .catalog import Catalog, read_json
from .errors import ContractError
from .models import CampaignRef, CampaignSpec, EvidenceBundle, TargetDefinition
from .paths import ROOT, RUNS_ROOT
from .runners.factory import create_runner
from .runners.openevolve_batch import DEFAULT_METHODS as OPENEVOLVE_METHODS
from .runtime import CommandExecutor, RuntimeManager, command_text
from .state import (
    STATE_FILE,
    campaign_ref_from_state,
    create_agent_state,
    load_agent_state,
    resolve_campaign_path,
    update_observation,
    update_phase,
    write_json_atomic,
)


SAFE_ID = re.compile(r"[a-z0-9][a-z0-9-]*")


def timestamp() -> str:
    return datetime.now().astimezone().strftime("%Y%m%d-%H%M")


class BenchmarkAgent:
    def __init__(
        self,
        *,
        catalog: Catalog | None = None,
        executor: CommandExecutor | None = None,
        runtime: RuntimeManager | None = None,
    ) -> None:
        self.catalog = catalog or Catalog()
        self.executor = executor or CommandExecutor()
        self.runtime = runtime or RuntimeManager()

    def resolve_targets(
        self,
        *,
        target_ids: Iterable[str] = (),
        preset_id: str | None = None,
    ) -> tuple[tuple[TargetDefinition, ...], Any | None]:
        ids = tuple(target_ids)
        if ids and preset_id:
            raise ContractError("use either --preset or --benchmark, not both")
        preset = self.catalog.presets.get(preset_id) if preset_id else None
        if preset_id and preset is None:
            raise ContractError(f"unknown preset: {preset_id}")
        ids = ids or (preset.benchmarks if preset else ())
        if not ids:
            raise ContractError("choose --benchmark or --preset")
        if len(set(ids)) != len(ids):
            raise ContractError("benchmark ids must be unique")
        unknown = set(ids) - set(self.catalog.targets)
        if unknown:
            raise ContractError("unknown benchmark target(s): " + ", ".join(sorted(unknown)))
        if preset:
            self._validate_preset_profile(preset)
        return tuple(self.catalog.targets[item] for item in ids), preset

    def resolve_spec(
        self,
        *,
        target_ids: Iterable[str] = (),
        preset_id: str | None = None,
        profile: str | None = None,
        campaign_id: str | None = None,
        campaign_dir: Path | None = None,
        methods: Iterable[str] = (),
        conditions: Iterable[str] = (),
        seeds: Iterable[int] = (),
        model: str | None = None,
        reasoning_effort: str | None = None,
        wall_time_seconds: int | None = None,
        live_search_concurrency: int | None = None,
        cell_concurrency: int | None = None,
        worker_runtime_seconds: int | None = None,
        worker_min_runtime_seconds: int | None = None,
    ) -> CampaignSpec:
        targets, preset = self.resolve_targets(target_ids=target_ids, preset_id=preset_id)
        runners = {item.runner_id for item in targets}
        if len(runners) != 1:
            raise ContractError("one campaign cannot mix different runner families")
        runner_definition = self.catalog.runners[next(iter(runners))]
        if runner_definition.kind == "native-profile" and len(targets) != 1:
            raise ContractError("native-profile campaigns accept exactly one benchmark")
        selected_profile = profile or (preset.profile if preset else None)
        selected_methods = tuple(methods)
        selected_seeds = tuple(seeds) or (1,)
        selected_conditions = tuple(conditions)
        values = (
            wall_time_seconds,
            live_search_concurrency,
            cell_concurrency,
            worker_runtime_seconds,
            worker_min_runtime_seconds,
            *selected_seeds,
        )
        if any(value is not None and value < 1 for value in values):
            raise ContractError("T, K, C, and seeds must be positive integers")
        if len(set(selected_seeds)) != len(selected_seeds):
            raise ContractError("seeds must be unique")
        if len(set(selected_conditions)) != len(selected_conditions):
            raise ContractError("conditions must be unique")

        if preset:
            expected = preset.expected_profile
            overrides = {
                "model": model,
                "reasoning_effort": reasoning_effort,
                "wall_time_seconds": wall_time_seconds,
                "concurrency": live_search_concurrency,
                "cell_concurrency": cell_concurrency,
            }
            drift = {
                key: {"expected": expected.get(key), "requested": value}
                for key, value in overrides.items()
                if value is not None and value != expected.get(key)
            }
            if selected_methods and list(selected_methods) != expected.get("methods"):
                drift["methods"] = {
                    "expected": expected.get("methods"),
                    "requested": list(selected_methods),
                }
            if drift:
                raise ContractError(
                    f"preset {preset.preset_id} is frozen; use --benchmark for overrides:\n"
                    + json.dumps(drift, indent=2)
                )
            selected_methods = selected_methods or tuple(expected.get("methods") or ())
            model = model if model is not None else expected.get("model")
            reasoning_effort = (
                reasoning_effort
                if reasoning_effort is not None
                else expected.get("reasoning_effort")
            )
            wall_time_seconds = (
                wall_time_seconds
                if wall_time_seconds is not None
                else expected.get("wall_time_seconds")
            )
            live_search_concurrency = (
                live_search_concurrency
                if live_search_concurrency is not None
                else expected.get("concurrency")
            )
            cell_concurrency = (
                cell_concurrency
                if cell_concurrency is not None
                else expected.get("cell_concurrency")
            )

        if runner_definition.kind == "native-profile" and not selected_profile:
            raise ContractError("native-profile campaigns require --profile or a preset")
        if (
            cell_concurrency is not None
            and cell_concurrency > 1
            and not runner_definition.capabilities.cell_concurrency
        ):
            raise ContractError(
                f"{runner_definition.runner_id} has not proven cross-cell "
                "concurrency; use C=1"
            )
        if runner_definition.kind in {"common-matrix", "openevolve-batch"}:
            required = {
                "--model": model,
                "--reasoning-effort": reasoning_effort,
                "--wall-time-seconds": wall_time_seconds,
                "--live-search-concurrency": live_search_concurrency,
            }
            missing = [flag for flag, value in required.items() if value is None]
            if missing:
                raise ContractError("common-matrix requires " + ", ".join(missing))
            cell_concurrency = 1
            if (
                worker_min_runtime_seconds is not None
                and worker_runtime_seconds is not None
                and worker_min_runtime_seconds > worker_runtime_seconds
            ):
                raise ContractError(
                    "worker minimum runtime cannot exceed worker maximum runtime"
                )
        if (
            runner_definition.kind == "common-matrix"
            and selected_methods
            and selected_conditions
        ):
            raise ContractError("common-matrix accepts --method or --condition, not both")
        if runner_definition.kind == "openevolve-batch" and len(selected_seeds) != 1:
            raise ContractError("openevolve-batch currently supports one seed per campaign")
        if runner_definition.kind == "openevolve-batch" and not selected_methods:
            selected_methods = OPENEVOLVE_METHODS
        if len(set(selected_methods)) != len(selected_methods):
            raise ContractError("methods must be unique")
        unsupported_methods = set(selected_methods) - set(
            runner_definition.supported_methods
        )
        if unsupported_methods:
            supported = ", ".join(runner_definition.supported_methods)
            rejected = ", ".join(sorted(unsupported_methods))
            raise ContractError(
                f"runner {runner_definition.runner_id} does not support method(s): "
                f"{rejected}; supported: {supported}"
            )

        selected_id = campaign_id
        if not selected_id and preset and preset.campaign_id_template:
            selected_id = preset.campaign_id_template.format(timestamp=timestamp())
        selected_id = selected_id or f"{'-'.join(item.target_id for item in targets)}-{timestamp()}"
        if SAFE_ID.fullmatch(selected_id) is None:
            raise ContractError(f"unsafe campaign id: {selected_id!r}")
        return CampaignSpec(
            campaign_id=selected_id,
            targets=targets,
            runner=runner_definition,
            preset_id=preset.preset_id if preset else None,
            profile=selected_profile,
            methods=selected_methods,
            conditions=selected_conditions,
            seeds=selected_seeds,
            model=model,
            reasoning_effort=reasoning_effort,
            wall_time_seconds=wall_time_seconds,
            live_search_concurrency=live_search_concurrency,
            cell_concurrency=cell_concurrency,
            worker_runtime_seconds=worker_runtime_seconds,
            worker_min_runtime_seconds=worker_min_runtime_seconds,
            campaign_dir=campaign_dir,
        )

    def setup(
        self,
        targets: tuple[TargetDefinition, ...],
        *,
        profile: str | None,
        skip_bootstrap: bool,
        skip_provision: bool,
        dry_run: bool,
    ) -> dict[str, Any]:
        warnings = self.runtime.validate_host(
            targets, dry_run=dry_run, require_uv=not skip_bootstrap
        )
        commands = self.runtime.setup_commands(
            targets,
            skip_bootstrap=skip_bootstrap,
            skip_provision=skip_provision,
        )
        groups: dict[str, list[TargetDefinition]] = {}
        for target in targets:
            groups.setdefault(target.runner_id, []).append(target)
        for runner_id, members in groups.items():
            definition = self.catalog.runners[runner_id]
            runner = create_runner(definition)
            if definition.capabilities.provision:
                spec = CampaignSpec(
                    campaign_id="setup",
                    targets=tuple(members),
                    runner=definition,
                    profile=profile,
                )
                commands.extend(
                    runner.provision_commands(
                        spec, skip_provision=skip_provision
                    )
                )
        result = {
            "schema_version": 1,
            "action": "setup",
            "benchmarks": [item.target_id for item in targets],
            "profile": profile,
            "docker": [item.docker.as_dict() for item in targets],
            "warnings": warnings,
            "commands": [command_text(item) for item in commands],
        }
        self.executor.execute(commands, dry_run=dry_run)
        if not dry_run and not (ROOT / ".bench-env/state.json").is_file():
            raise ContractError("setup completed without .bench-env/state.json")
        return result

    def start(
        self,
        spec: CampaignSpec,
        *,
        skip_bootstrap: bool,
        skip_provision: bool,
        prepare_only: bool,
        foreground: bool,
        dry_run: bool,
    ) -> dict[str, Any]:
        warnings = self.runtime.validate_host(
            spec.targets, dry_run=dry_run, require_uv=not skip_bootstrap
        )
        runner = create_runner(spec.runner)
        setup_commands = self.runtime.setup_commands(
            spec.targets,
            skip_bootstrap=skip_bootstrap,
            skip_provision=skip_provision,
        )
        setup_commands.extend(
            runner.provision_commands(spec, skip_provision=skip_provision)
        )
        prepare_commands, campaign = runner.prepare_commands(spec)
        detach = spec.runner.capabilities.detach and not foreground
        run_commands = [] if prepare_only else [runner.start_command(spec, campaign, detach=detach)]
        commands = [*setup_commands, *prepare_commands, *run_commands]
        follow_up = self._follow_up(campaign, spec.runner.capabilities)
        plan = {
            "schema_version": 1,
            "action": "start",
            "resolved_spec": spec.as_dict(),
            "campaign": campaign.as_dict(),
            "docker": [item.docker.as_dict() for item in spec.targets],
            "warnings": warnings,
            "commands": [command_text(item) for item in commands],
            "follow_up": follow_up,
        }
        if dry_run:
            self.executor.execute(commands, dry_run=True)
            return plan

        self.executor.execute(setup_commands, dry_run=False)
        self.executor.execute(prepare_commands, dry_run=False)
        if not campaign.path.is_dir() or not (campaign.path / "campaign.json").is_file():
            raise ContractError(f"runner did not create campaign state: {campaign.path}")
        state = create_agent_state(
            spec,
            campaign,
            commands=plan["commands"],
            follow_up=follow_up,
        )
        if run_commands:
            try:
                self.executor.execute(run_commands, dry_run=False)
                if detach:
                    state = update_phase(campaign.path, state, "running")
            finally:
                state = update_observation(campaign.path, state, runner.status(campaign))
        plan["agent_state"] = str(campaign.path / STATE_FILE)
        plan["agent_phase"] = state["agent_phase"]
        return plan

    def status(self, campaign_value: str | Path, *, benchmark: str | None = None) -> dict[str, Any]:
        campaign, state, ref, runner = self._campaign_context(campaign_value, benchmark)
        snapshot = runner.status(ref)
        state = update_observation(campaign, state, snapshot)
        return {
            "campaign": ref.as_dict(),
            "agent_phase": state["agent_phase"],
            "runner": snapshot.as_dict(),
            "follow_up": state.get("follow_up", {}),
            "artifacts": state.get("artifacts", {}),
        }

    def stop(self, campaign_value: str | Path, *, benchmark: str | None, dry_run: bool) -> dict[str, Any]:
        campaign, state, ref, runner = self._campaign_context(campaign_value, benchmark)
        command = runner.stop_command(ref)
        if dry_run:
            self.executor.execute([command], dry_run=True)
        else:
            try:
                self.executor.execute([command], dry_run=False)
            finally:
                state = update_observation(campaign, state, runner.status(ref))
        return {"campaign": ref.as_dict(), "command": command_text(command), "agent_phase": state["agent_phase"]}

    def resume(self, campaign_value: str | Path, *, benchmark: str | None, dry_run: bool) -> dict[str, Any]:
        campaign, state, ref, runner = self._campaign_context(campaign_value, benchmark)
        command = runner.resume_command(state, ref)
        if dry_run:
            self.executor.execute([command], dry_run=True)
        else:
            try:
                self.executor.execute([command], dry_run=False)
            finally:
                state = update_observation(campaign, state, runner.status(ref))
        return {"campaign": ref.as_dict(), "command": command_text(command), "agent_phase": state["agent_phase"]}

    def finish(
        self,
        campaign_value: str | Path,
        *,
        benchmark: str | None,
        markdown_out: Path | None,
        xlsx_out: Path | None,
        dry_run: bool,
    ) -> dict[str, Any]:
        campaign, state, ref, runner = self._campaign_context(campaign_value, benchmark)
        snapshot = runner.status(ref)
        if not snapshot.terminal:
            raise ContractError(f"campaign is not terminal: state={snapshot.raw_state!r}")
        finalize = runner.finalize_command(ref)
        report = [sys.executable, "scripts/benchmark_report.py", "--campaign", str(campaign)]
        if markdown_out:
            report.extend(["--markdown-out", str(markdown_out.expanduser().resolve())])
        if xlsx_out:
            report.extend(["--xlsx-out", str(xlsx_out.expanduser().resolve())])
        if dry_run:
            self.executor.execute([finalize, report], dry_run=True)
        else:
            self.executor.execute([finalize], dry_run=False)
            state = update_phase(campaign, state, "finalized")
            self.executor.execute([report], dry_run=False)
        markdown = markdown_out.expanduser().resolve() if markdown_out else campaign / "report.md"
        workbook = xlsx_out.expanduser().resolve() if xlsx_out else campaign / f"{campaign.name}.xlsx"
        evidence = EvidenceBundle(runner.evidence_source(ref), markdown, workbook)
        if not dry_run:
            missing = [path for path in (evidence.source, evidence.markdown, evidence.workbook) if not path.is_file()]
            if missing:
                raise ContractError("finish did not create: " + ", ".join(str(path) for path in missing))
            state = update_phase(campaign, state, "reported", evidence=evidence)
        return {
            "campaign": ref.as_dict(),
            "agent_phase": state["agent_phase"],
            "artifacts": evidence.as_dict(),
            "commands": [command_text(finalize), command_text(report)],
        }

    def check(self, target_id: str, *, dry_run: bool) -> dict[str, Any]:
        try:
            target = self.catalog.targets[target_id]
        except KeyError as error:
            raise ContractError(f"unknown benchmark target: {target_id}") from error
        loaded = load_adapter(target.adapter_id) if target.adapter_id else None
        adapter = loaded.manifest_contract() if loaded else None
        if loaded and target.docker.provision_mode == "eager":
            missing_hooks = [
                name
                for name in ("provision_environment", "doctor_environment")
                if not callable(getattr(loaded.module, name, None))
            ]
            if missing_hooks:
                raise ContractError(
                    f"{target_id}: eager adapter Docker is missing "
                    + ", ".join(missing_hooks)
                )
        command = [sys.executable, "scripts/status.py", "--check"]
        self.executor.execute([command], dry_run=dry_run)
        return {
            "benchmark": target.as_dict(),
            "runner": self.catalog.runners[target.runner_id].as_dict(),
            "adapter": adapter,
            "repository_check": command_text(command),
            "validated": not dry_run,
        }

    def _campaign_context(self, value: str | Path, benchmark: str | None):
        campaign = resolve_campaign_path(value)
        if not (campaign / STATE_FILE).is_file():
            if not benchmark:
                raise ContractError(
                    f"{STATE_FILE} is missing; pass --benchmark once to adopt this legacy campaign"
                )
            self._adopt_legacy(campaign, benchmark)
        state = load_agent_state(campaign)
        ref = campaign_ref_from_state(campaign, state)
        try:
            definition = self.catalog.runners[ref.runner_id]
        except KeyError as error:
            raise ContractError(f"agent state names unknown runner {ref.runner_id!r}") from error
        return campaign, state, ref, create_runner(definition)

    def _adopt_legacy(self, campaign: Path, benchmark: str) -> None:
        try:
            target = self.catalog.targets[benchmark]
        except KeyError as error:
            raise ContractError(f"unknown benchmark target: {benchmark}") from error
        manifest = read_json(campaign / "campaign.json")
        runner = create_runner(self.catalog.runners[target.runner_id])
        ref = CampaignRef(str(manifest.get("campaign_id") or campaign.name), campaign, target.target_id, target.runner_id)
        snapshot = runner.status(ref)
        phase = "terminal" if snapshot.terminal else ("running" if snapshot.state == "running" else "prepared")
        payload = {
            "schema_version": 1,
            "campaign_id": ref.campaign_id,
            "campaign_path": str(campaign),
            "target_id": target.target_id,
            "runner_id": target.runner_id,
            "agent_phase": phase,
            "created_at": datetime.now().astimezone().isoformat(),
            "updated_at": datetime.now().astimezone().isoformat(),
            "resolved_spec": {
                "campaign_id": ref.campaign_id,
                "targets": manifest.get("benchmarks") or [target.target_id],
                "model": manifest.get("model"),
                "reasoning_effort": manifest.get("reasoning_effort"),
                "methods": manifest.get("methods") or [],
                "concurrency": manifest.get("budget") or {},
                "adopted": True,
            },
            "runner_manifest": "campaign.json",
            "commands": [],
            "follow_up": self._follow_up(ref, self.catalog.runners[target.runner_id].capabilities),
            "last_observed": snapshot.as_dict(),
            "artifacts": {},
            "secret_policy": "credentials are inherited only and are never serialized",
        }
        write_json_atomic(campaign / STATE_FILE, payload)

    @staticmethod
    def _follow_up(campaign: CampaignRef, capabilities: Any) -> dict[str, str]:
        base = [sys.executable, "scripts/bench.py"]
        result = {
            "status": command_text([*base, "status", "--campaign", str(campaign.path)]),
            "finish": command_text([*base, "finish", "--campaign", str(campaign.path)]),
        }
        if capabilities.stop:
            result["stop"] = command_text([*base, "stop", "--campaign", str(campaign.path)])
        if capabilities.resume:
            result["resume"] = command_text([*base, "resume", "--campaign", str(campaign.path)])
        return result

    @staticmethod
    def _validate_preset_profile(preset: Any) -> None:
        if not preset.expected_profile or not preset.profile:
            return
        profile = read_json(ROOT / "experiments/edgebench/profiles" / f"{preset.profile}.json")
        observed = {
            "task_count": len(profile.get("task_ids", [])),
            "methods": profile.get("methods"),
            "model": profile.get("model"),
            "reasoning_effort": profile.get("reasoning_effort"),
            "wall_time_seconds": profile.get("wall_time_seconds"),
            "concurrency": profile.get("concurrency"),
            "cell_concurrency": profile.get("cell_concurrency"),
        }
        if observed != preset.expected_profile:
            raise ContractError(
                f"preset {preset.preset_id} profile drifted:\n"
                + json.dumps({"expected": preset.expected_profile, "observed": observed}, indent=2)
            )

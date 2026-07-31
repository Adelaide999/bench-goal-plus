"""Runner interface implemented by native and common benchmark controllers."""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from ..models import (
    CampaignRef,
    CampaignSpec,
    EvidenceBundle,
    RunnerDefinition,
    StatusSnapshot,
)


class BenchmarkRunner(ABC):
    def __init__(self, definition: RunnerDefinition) -> None:
        self.definition = definition

    @abstractmethod
    def provision_commands(
        self, spec: CampaignSpec, *, skip_provision: bool
    ) -> list[list[str]]: ...

    @abstractmethod
    def prepare_commands(self, spec: CampaignSpec) -> tuple[list[list[str]], CampaignRef]: ...

    @abstractmethod
    def start_command(self, spec: CampaignSpec, campaign: CampaignRef, *, detach: bool) -> list[str]: ...

    @abstractmethod
    def resume_command(self, state: dict, campaign: CampaignRef) -> list[str]: ...

    @abstractmethod
    def status(self, campaign: CampaignRef) -> StatusSnapshot: ...

    @abstractmethod
    def stop_command(self, campaign: CampaignRef) -> list[str]: ...

    @abstractmethod
    def finalize_command(self, campaign: CampaignRef) -> list[str]: ...

    @abstractmethod
    def evidence_source(self, campaign: CampaignRef) -> Path: ...

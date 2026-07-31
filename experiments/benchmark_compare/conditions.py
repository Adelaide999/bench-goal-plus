"""Canonical ablation conditions for standalone benchmark comparisons."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


ConditionId = Literal["B0", "B1", "B2", "B3", "B4"]
CoordinationVariant = Literal["way0", "way1", "way2"]


@dataclass(frozen=True)
class Condition:
    condition_id: ConditionId
    method: str | None
    shared_final: bool
    shared_evidence: bool
    plan_visible: bool
    reject_enabled: bool
    evidence_updates: bool
    same_agent_resume: bool
    search_space_mode: str | None
    coordination_variant: CoordinationVariant | None
    implemented: bool = True
    limitation: str | None = None

    def effective_concurrency(self, requested: int) -> int:
        if requested < 1:
            raise ValueError("concurrency must be positive")
        return 1 if self.condition_id == "B0" else requested

    def as_manifest(self) -> dict[str, object]:
        return {
            "id": self.condition_id,
            "method": self.method,
            "implemented": self.implemented,
            "shared_final": self.shared_final,
            "shared_evidence": self.shared_evidence,
            "plan_visible": self.plan_visible,
            "reject_enabled": self.reject_enabled,
            "evidence_updates": self.evidence_updates,
            "same_agent_resume": self.same_agent_resume,
            "search_space_mode": self.search_space_mode,
            "coordination_variant": self.coordination_variant,
            "limitation": self.limitation,
        }


CONDITIONS: dict[ConditionId, Condition] = {
    "B0": Condition(
        "B0", "plain-codex", False, False, False, False, False, False, None, None
    ),
    "B1": Condition(
        "B1", "plain-codex", False, False, False, False, False, False, None, None
    ),
    "B2": Condition(
        "B2",
        None,
        True,
        False,
        False,
        False,
        False,
        False,
        None,
        None,
        implemented=False,
        limitation=(
            "Goal Plus currently exposes full run history to candidate contexts; it has no "
            "runtime switch that exposes only final/best results while hiding intermediate evidence"
        ),
    ),
    "B3": Condition(
        "B3", "goal-plus-codex", True, True, True, False, True, True, "observe", "way2"
    ),
    "B4": Condition(
        "B4", "goal-plus-codex", True, True, True, True, True, True, "enforce", "way1"
    ),
}

VARIANT_LIMITATIONS: dict[CoordinationVariant, str | None] = {
    "way0": (
        "the runtime does not currently hide plans and suppress Evidence updates while "
        "retaining reject/admission"
    ),
    "way1": None,
    "way2": None,
}


def resolve_condition(
    *,
    method: str,
    concurrency: int,
    condition_id: str | None = None,
    coordination_variant: str | None = None,
) -> Condition | None:
    """Resolve explicit or backward-compatible condition semantics."""
    if concurrency < 1:
        raise ValueError("concurrency must be positive")
    if condition_id is None:
        if coordination_variant is not None:
            raise ValueError("--coordination-variant requires --condition")
        if method == "plain-codex":
            return CONDITIONS["B0" if concurrency == 1 else "B1"]
        # Preserve the historical Goal Plus prompt when no ablation condition is
        # frozen. It may share run history, but it cannot be claimed as B4 unless
        # the run explicitly opens and verifies an enforce-mode Search Space.
        return None
    if condition_id not in CONDITIONS:
        raise ValueError(f"unknown benchmark condition: {condition_id}")
    condition = CONDITIONS[condition_id]  # type: ignore[index]
    if not condition.implemented:
        raise ValueError(f"{condition.condition_id} is not implemented: {condition.limitation}")
    if condition.method != method:
        raise ValueError(
            f"{condition.condition_id} requires --method {condition.method}, got {method}"
        )
    if condition.condition_id == "B0" and concurrency != 1:
        raise ValueError("B0 requires --concurrency 1")
    if condition.condition_id in {"B1", "B3", "B4"} and concurrency < 2:
        raise ValueError(f"{condition.condition_id} requires --concurrency >= 2")
    if coordination_variant is not None:
        if coordination_variant not in VARIANT_LIMITATIONS:
            raise ValueError(f"unknown coordination variant: {coordination_variant}")
        limitation = VARIANT_LIMITATIONS[coordination_variant]  # type: ignore[index]
        if limitation:
            raise ValueError(f"{coordination_variant} is not implemented: {limitation}")
        if condition.coordination_variant != coordination_variant:
            raise ValueError(
                f"{condition.condition_id} maps to {condition.coordination_variant}, "
                f"not {coordination_variant}"
            )
    return condition

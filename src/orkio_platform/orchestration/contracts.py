from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from orkio_platform.domain.models import InteractionMode


@dataclass(frozen=True, slots=True)
class CapabilityDefinition:
    capability_id: str
    agent_id: str
    description: str
    inputs: tuple[str, ...]
    outputs: tuple[str, ...]
    permissions: tuple[str, ...]
    risk_level: str
    governance_required: bool
    runtime: str
    status: str
    version: str
    availability: str = "available"
    evidence: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()
    human_approval_required: bool = False


@dataclass(frozen=True, slots=True)
class OrchestrationPlan:
    requested_agent: str
    owner_agent: str
    contributors: tuple[str, ...]
    route_family: str
    interaction_mode: InteractionMode
    trace_kind: str = "trace_lite"

    @property
    def multiagent(self) -> bool:
        return bool(self.contributors)


ContributionStatus = Literal[
    "success",
    "refused",
    "contract_violation",
    "failed",
]


@dataclass(frozen=True, slots=True)
class AgentContribution:
    agent_id: str
    display_name: str
    content: str
    provider: str
    model: str
    response_id: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None
    status: ContributionStatus = "success"
    status_reason: str | None = None
    retry_count: int = 0
    latency_ms: int | None = None
    output_normalized: bool = False
    budget_exceeded: bool = False
    contract_version: str = "agent_contribution_v2"
    assigned_task: str | None = None
    task_slice_version: str | None = None
    explicit_assignment: bool = False

    def token_usage(self) -> dict[str, int] | None:
        values = {
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.total_tokens,
        }
        normalized = {
            key: value
            for key, value in values.items()
            if value is not None
        }
        return normalized or None

    @property
    def validated(self) -> bool:
        return self.status == "success"

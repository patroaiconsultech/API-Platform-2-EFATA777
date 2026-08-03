from __future__ import annotations

from dataclasses import dataclass


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


@dataclass(frozen=True, slots=True)
class OrchestrationPlan:
    requested_agent: str
    owner_agent: str
    contributors: tuple[str, ...]
    route_family: str
    trace_kind: str = "trace_lite"

    @property
    def multiagent(self) -> bool:
        return bool(self.contributors)


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

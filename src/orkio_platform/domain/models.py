from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"


ExecutionStatus = Literal["running", "success", "error", "cancelled"]
RecoveryDecision = Literal["retry", "cancel", "abandon"]
InteractionMode = Literal["single", "team_synthesis", "roundtable"]


class PrincipalContext(BaseModel):
    model_config = ConfigDict(frozen=True)
    tenant_id: str = Field(min_length=1)
    user_id: str = Field(min_length=1)
    role: Literal["member", "admin", "auditor"] = "member"


class Agent(BaseModel):
    model_config = ConfigDict(frozen=True)
    agent_id: str
    display_name: str
    description: str
    status: Literal["active", "disabled"] = "active"
    capabilities: tuple[str, ...] = ()


class ThreadRecord(BaseModel):
    model_config = ConfigDict(frozen=True)
    thread_id: str
    tenant_id: str
    created_by: str
    title: str
    created_at: datetime = Field(default_factory=utc_now)


class MessageRecord(BaseModel):
    model_config = ConfigDict(frozen=True)
    message_id: str
    thread_id: str
    tenant_id: str
    user_id: str
    role: Literal["user", "assistant", "system"]
    content: str
    agent_id: str | None = None
    agent_name: str | None = None
    display_name: str | None = None
    final_speaker: str | None = None
    turn_owner: str | None = None
    request_id: str | None = None
    execution_id: str | None = None
    route_family: str | None = None
    status: Literal["success", "error", "cancelled"] | None = None
    error_code: str | None = None
    error_message: str | None = None
    created_at: datetime = Field(default_factory=utc_now)


class ExecutionRecord(BaseModel):
    model_config = ConfigDict(frozen=True)
    tenant_id: str
    request_id: str
    execution_id: str
    thread_id: str
    user_id: str
    requested_agent: str
    resolved_agent: str
    turn_owner: str
    display_name: str
    route_family: str
    request_fingerprint_sha256: str
    status: ExecutionStatus = "running"
    lease_owner: str
    lease_expires_at: datetime
    heartbeat_at: datetime
    error_code: str | None = None
    error_message: str | None = None
    user_message_id: str | None = None
    assistant_message_id: str | None = None
    started_at: datetime = Field(default_factory=utc_now)
    completed_at: datetime | None = None


class RecoveryDecisionRecord(BaseModel):
    model_config = ConfigDict(frozen=True)
    tenant_id: str
    decision_id: str
    request_id: str
    execution_id: str
    actor_id: str
    decision: RecoveryDecision
    reason: str = Field(min_length=1, max_length=1000)
    created_at: datetime = Field(default_factory=utc_now)


class AgentTurnContext(BaseModel):
    model_config = ConfigDict(frozen=True)
    request_id: str
    execution_id: str
    thread_id: str
    tenant_id: str
    user_id: str
    requested_agent: str
    resolved_agent: str
    turn_owner: str
    display_agent: str
    route_family: str
    interaction_mode: InteractionMode = "single"
    contributing_agents: tuple[str, ...] = ()
    trace_kind: Literal["trace_lite"] = "trace_lite"
    ownership_locked: bool = True
    governance_mode: str = "controlled_execution"
    write_allowed: bool = True
    execution_allowed: bool = True

    @model_validator(mode="after")
    def validate_locked_owner(self) -> "AgentTurnContext":
        if self.ownership_locked and self.resolved_agent != self.turn_owner:
            raise ValueError("AGENT_OWNERSHIP_DIVERGENCE")
        return self


class ResponseEnvelope(BaseModel):
    model_config = ConfigDict(frozen=True)
    message_id: str
    request_id: str
    execution_id: str
    thread_id: str
    tenant_id: str
    agent_id: str
    agent_name: str
    display_name: str
    final_speaker: str
    turn_owner: str
    route_family: str
    interaction_mode: InteractionMode = "single"
    content: str
    status: Literal["success", "error", "cancelled"]
    error: dict[str, Any] | None = None
    token_usage: dict[str, int] | None = None
    execution_trace: list[dict[str, Any]] | None = None
    contributions: list[dict[str, Any]] | None = None
    owner_contract: dict[str, Any] | None = None
    budget: dict[str, Any] | None = None
    knowledge_snapshot_version: str | None = None
    transport: Literal["http_json", "sse"] = "http_json"
    terminal_source: Literal["envelope", "wire"] = "envelope"
    latency_ms: int | None = None
    created_at: datetime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def validate_identity(self) -> "ResponseEnvelope":
        canonical = {
            self.agent_id,
            self.agent_name,
            self.final_speaker,
            self.turn_owner,
        }
        if len(canonical) != 1:
            raise ValueError("PERSISTENCE_AGENT_MISMATCH")
        return self


class ThreadCreate(BaseModel):
    title: str = Field(min_length=1, max_length=160)


class ChatRequest(BaseModel):
    thread_id: str
    content: str = Field(min_length=1, max_length=100_000)
    requested_agent: str | None = None
    interaction_mode: InteractionMode | None = None
    request_id: str | None = None
    simulate_error: bool = False


class CancelExecutionRequest(BaseModel):
    reason: str = Field(
        default="Cancelled by an authorized user.",
        min_length=1,
        max_length=1000,
    )


class RecoveryDecisionCreate(BaseModel):
    decision: RecoveryDecision
    reason: str = Field(min_length=1, max_length=1000)


class EvolutionProposalRequest(BaseModel):
    objective: str = Field(min_length=1, max_length=20_000)
    evidence: tuple[str, ...] = ()
    constraints: tuple[str, ...] = ()
    requested_agent: Literal["Orion", "Team"] = "Orion"


class EvolutionProposalEnvelope(BaseModel):
    model_config = ConfigDict(frozen=True)
    proposal_id: str
    tenant_id: str
    requested_by: str
    status: Literal["proposal_only"] = "proposal_only"
    content: str
    provider: str
    model: str
    token_usage: dict[str, int] | None = None
    write_executed: bool = False
    commit_executed: bool = False
    merge_executed: bool = False
    deploy_executed: bool = False
    migration_executed: bool = False
    human_approval_required: bool = True
    created_at: datetime = Field(default_factory=utc_now)


class SSEEvent(BaseModel):
    model_config = ConfigDict(frozen=True)
    event_id: str
    event_type: str
    execution_id: str
    tenant_id: str
    thread_id: str
    agent_id: str
    turn_owner: str
    sequence: int
    payload: dict[str, Any]
    created_at: datetime = Field(default_factory=utc_now)

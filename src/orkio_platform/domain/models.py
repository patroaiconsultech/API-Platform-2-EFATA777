from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"


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
    execution_id: str | None = None
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
    ownership_locked: bool = True
    governance_mode: str = "controlled_execution"
    write_allowed: bool = True
    execution_allowed: bool = True

    @model_validator(mode="after")
    def validate_locked_owner(self) -> "AgentTurnContext":
        if self.ownership_locked:
            identities = {
                self.resolved_agent,
                self.turn_owner,
                self.display_agent,
            }
            if len(identities) != 1:
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
    content: str
    status: Literal["success", "error", "cancelled"]
    error: dict[str, Any] | None = None
    token_usage: dict[str, int] | None = None
    latency_ms: int | None = None
    created_at: datetime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def validate_identity(self) -> "ResponseEnvelope":
        values = {
            self.agent_id,
            self.agent_name,
            self.display_name,
            self.final_speaker,
            self.turn_owner,
        }
        if len(values) != 1:
            raise ValueError("PERSISTENCE_AGENT_MISMATCH")
        return self


class ThreadCreate(BaseModel):
    title: str = Field(min_length=1, max_length=160)


class ChatRequest(BaseModel):
    thread_id: str
    content: str = Field(min_length=1, max_length=100_000)
    requested_agent: str | None = None
    simulate_error: bool = False


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

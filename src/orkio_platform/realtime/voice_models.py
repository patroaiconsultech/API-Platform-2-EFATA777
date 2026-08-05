from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from orkio_platform.domain.models import ResponseEnvelope, utc_now


VoiceSessionStatus = Literal[
    "created",
    "connecting",
    "connected",
    "listening",
    "processing",
    "speaking",
    "error",
    "closing",
    "closed",
]
VoiceTurnStatus = Literal[
    "created",
    "accepted",
    "processing",
    "completed",
    "failed",
    "interrupted",
]
VoiceEventSource = Literal[
    "browser",
    "provider",
    "backend",
    "agent_runtime",
]
VoiceCloseReason = Literal[
    "user_end",
    "timeout",
    "fatal_error",
    "revoked",
    "replaced",
]
VoiceAudioStatus = Literal[
    "pending",
    "speaking",
    "completed",
    "interrupted",
    "failed",
]


class VoiceSessionRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    tenant_id: str = Field(min_length=1, max_length=120)
    session_id: str = Field(min_length=1, max_length=120)
    thread_id: str = Field(min_length=1, max_length=120)
    user_id: str = Field(min_length=1, max_length=120)
    requested_agent: Literal["Orkio"] = "Orkio"
    resolved_agent: Literal["Orkio"] = "Orkio"
    turn_owner: Literal["Orkio"] = "Orkio"
    ownership_locked: Literal[True] = True
    status: VoiceSessionStatus = "created"
    session_generation: int = Field(default=1, ge=1)
    provider: str = Field(min_length=1, max_length=80)
    provider_call_id: str | None = Field(default=None, max_length=200)
    source_connection_id: str | None = Field(default=None, max_length=200)
    last_canonical_sequence: int = Field(default=0, ge=0)
    reconnect_attempts: int = Field(default=0, ge=0)
    created_at: datetime = Field(default_factory=utc_now)
    connected_at: datetime | None = None
    closed_at: datetime | None = None
    close_reason: VoiceCloseReason | None = None
    microphone_released: bool = False
    player_released: bool = False


class VoiceEventRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    tenant_id: str
    session_id: str
    event_id: str
    canonical_sequence: int = Field(ge=1)
    source: VoiceEventSource
    source_event_key: str
    event_type: str
    session_generation: int = Field(ge=1)
    source_sequence: int | None = Field(default=None, ge=0)
    source_connection_id: str | None = None
    turn_id: str | None = None
    execution_id: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utc_now)


class VoiceTurnRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    tenant_id: str
    session_id: str
    turn_id: str
    transcript_id: str
    request_id: str
    execution_id: str | None = None
    response_envelope_id: str | None = None
    status: VoiceTurnStatus = "created"
    user_transcript: str
    assistant_content: str | None = None
    assistant_content_sha256: str | None = None
    tts_input_sha256: str | None = None
    audio_status: VoiceAudioStatus = "pending"
    spoken_content_complete: bool = False
    canonical_text_preserved: bool = True
    response_payload: dict[str, Any] | None = None
    error_code: str | None = None
    error_message: str | None = None
    created_at: datetime = Field(default_factory=utc_now)
    completed_at: datetime | None = None


class VoiceSessionCreateRequest(BaseModel):
    thread_id: str = Field(min_length=1, max_length=120)
    requested_agent: Literal["Orkio"] = "Orkio"
    interaction_mode: Literal["single"] = "single"
    consent_granted: bool = False

    @model_validator(mode="after")
    def require_consent(self) -> "VoiceSessionCreateRequest":
        if not self.consent_granted:
            raise ValueError("VOICE_CONSENT_REQUIRED")
        return self


class VoiceCallOfferRequest(BaseModel):
    sdp: str = Field(min_length=1, max_length=2_000_000)
    source_connection_id: str = Field(min_length=1, max_length=200)
    expected_session_generation: int = Field(default=1, ge=1)


class VoiceCallAnswer(BaseModel):
    session: VoiceSessionRecord
    sdp: str
    provider_call_id: str
    resume_token: str
    resume_token_expires_at: datetime


class VoiceResumeRequest(BaseModel):
    resume_token: str = Field(min_length=32, max_length=4096)
    expected_session_generation: int = Field(ge=1)
    source_connection_id: str = Field(min_length=1, max_length=200)
    last_received_canonical_sequence: int = Field(default=0, ge=0)


class VoiceEventAppendRequest(BaseModel):
    source: VoiceEventSource
    event_type: str = Field(min_length=1, max_length=200)
    session_generation: int = Field(ge=1)
    client_event_id: str | None = Field(default=None, max_length=200)
    provider_event_id: str | None = Field(default=None, max_length=200)
    source_sequence: int | None = Field(default=None, ge=0)
    source_connection_id: str | None = Field(default=None, max_length=200)
    turn_id: str | None = Field(default=None, max_length=120)
    execution_id: str | None = Field(default=None, max_length=120)
    payload: dict[str, Any] = Field(default_factory=dict)

    def source_event_key(self) -> str:
        if self.source == "provider":
            if not self.provider_event_id:
                raise ValueError("PROVIDER_EVENT_ID_REQUIRED")
            return self.provider_event_id
        if self.source == "browser":
            if not self.client_event_id:
                raise ValueError("CLIENT_EVENT_ID_REQUIRED")
            return self.client_event_id
        return self.client_event_id or self.provider_event_id or self.event_type


class VoiceTurnCreateRequest(BaseModel):
    transcript_id: str = Field(min_length=1, max_length=200)
    transcript: str = Field(min_length=1, max_length=100_000)
    client_event_id: str = Field(min_length=1, max_length=200)
    session_generation: int = Field(ge=1)


class VoiceTurnResult(BaseModel):
    turn: VoiceTurnRecord
    response: ResponseEnvelope
    assistant_content_sha256: str
    tts_input_sha256: str


class VoiceAudioReportRequest(BaseModel):
    provider_event_id: str = Field(min_length=1, max_length=200)
    session_generation: int = Field(ge=1)
    spoken_transcript: str = Field(default="", max_length=100_000)
    audio_status: VoiceAudioStatus
    response_id: str | None = Field(default=None, max_length=200)


class VoiceCloseRequest(BaseModel):
    close_reason: VoiceCloseReason
    microphone_released: Literal[True]
    player_released: Literal[True]
    expected_session_generation: int = Field(ge=1)


class VoiceSessionStatusEnvelope(BaseModel):
    session: VoiceSessionRecord
    events: list[VoiceEventRecord] = Field(default_factory=list)
    resume_token: str | None = None
    resume_token_expires_at: datetime | None = None

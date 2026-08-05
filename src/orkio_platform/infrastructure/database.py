from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    UniqueConstraint,
    create_engine,
)
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.pool import StaticPool

metadata = MetaData()

threads = Table(
    "threads",
    metadata,
    Column("tenant_id", String(120), primary_key=True),
    Column("thread_id", String(120), primary_key=True),
    Column("created_by", String(120), nullable=False),
    Column("title", String(160), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
)
Index("ix_threads_tenant_created_at", threads.c.tenant_id, threads.c.created_at)

executions = Table(
    "executions",
    metadata,
    Column("tenant_id", String(120), primary_key=True),
    Column("request_id", String(160), primary_key=True),
    Column("execution_id", String(120), nullable=False),
    Column("thread_id", String(120), nullable=False),
    Column("user_id", String(120), nullable=False),
    Column("requested_agent", String(120), nullable=False),
    Column("resolved_agent", String(120), nullable=False),
    Column("turn_owner", String(120), nullable=False),
    Column("display_name", String(160), nullable=False),
    Column("route_family", String(120), nullable=False),
    Column("request_fingerprint_sha256", String(64), nullable=False),
    Column("status", String(20), nullable=False),
    Column("lease_owner", String(120), nullable=False),
    Column("lease_expires_at", DateTime(timezone=True), nullable=False),
    Column("heartbeat_at", DateTime(timezone=True), nullable=False),
    Column("error_code", String(120)),
    Column("error_message", Text()),
    Column("user_message_id", String(120)),
    Column("assistant_message_id", String(120)),
    Column("started_at", DateTime(timezone=True), nullable=False),
    Column("completed_at", DateTime(timezone=True)),
    ForeignKeyConstraint(
        ["tenant_id", "thread_id"],
        ["threads.tenant_id", "threads.thread_id"],
        ondelete="CASCADE",
        name="fk_executions_thread_tenant",
    ),
    UniqueConstraint(
        "tenant_id",
        "execution_id",
        name="uq_executions_tenant_execution",
    ),
)
Index(
    "ix_executions_tenant_status",
    executions.c.tenant_id,
    executions.c.status,
)
Index(
    "ix_executions_lease_expiry",
    executions.c.tenant_id,
    executions.c.lease_expires_at,
)

messages = Table(
    "messages",
    metadata,
    Column("tenant_id", String(120), primary_key=True),
    Column("message_id", String(120), primary_key=True),
    Column("thread_id", String(120), nullable=False),
    Column("user_id", String(120), nullable=False),
    Column("role", String(20), nullable=False),
    Column("content", Text(), nullable=False),
    Column("agent_id", String(120)),
    Column("agent_name", String(120)),
    Column("display_name", String(160)),
    Column("final_speaker", String(120)),
    Column("turn_owner", String(120)),
    Column("request_id", String(160)),
    Column("execution_id", String(120)),
    Column("route_family", String(120)),
    Column("status", String(20)),
    Column("error_code", String(120)),
    Column("error_message", Text()),
    Column("created_at", DateTime(timezone=True), nullable=False),
    ForeignKeyConstraint(
        ["tenant_id", "thread_id"],
        ["threads.tenant_id", "threads.thread_id"],
        ondelete="CASCADE",
        name="fk_messages_thread_tenant",
    ),
    UniqueConstraint(
        "tenant_id",
        "execution_id",
        "role",
        name="uq_messages_tenant_execution_role",
    ),
)
Index(
    "ix_messages_tenant_thread_created_at",
    messages.c.tenant_id,
    messages.c.thread_id,
    messages.c.created_at,
)
Index("ix_messages_execution_id", messages.c.execution_id)

recovery_decisions = Table(
    "recovery_decisions",
    metadata,
    Column("tenant_id", String(120), primary_key=True),
    Column("decision_id", String(120), primary_key=True),
    Column("request_id", String(160), nullable=False),
    Column("execution_id", String(120), nullable=False),
    Column("actor_id", String(120), nullable=False),
    Column("decision", String(20), nullable=False),
    Column("reason", Text(), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    ForeignKeyConstraint(
        ["tenant_id", "request_id"],
        ["executions.tenant_id", "executions.request_id"],
        ondelete="CASCADE",
        name="fk_recovery_decisions_execution_request",
    ),
)
Index(
    "ix_recovery_decisions_request",
    recovery_decisions.c.tenant_id,
    recovery_decisions.c.request_id,
    recovery_decisions.c.created_at,
)


voice_sessions = Table(
    "voice_sessions",
    metadata,
    Column("tenant_id", String(120), primary_key=True),
    Column("session_id", String(120), primary_key=True),
    Column("thread_id", String(120), nullable=False),
    Column("user_id", String(120), nullable=False),
    Column("requested_agent", String(120), nullable=False),
    Column("resolved_agent", String(120), nullable=False),
    Column("turn_owner", String(120), nullable=False),
    Column("ownership_locked", Boolean(), nullable=False),
    Column("status", String(20), nullable=False),
    Column("session_generation", Integer(), nullable=False),
    Column("provider", String(80), nullable=False),
    Column("provider_call_id", String(200)),
    Column("source_connection_id", String(200)),
    Column("last_canonical_sequence", Integer(), nullable=False),
    Column("reconnect_attempts", Integer(), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("connected_at", DateTime(timezone=True)),
    Column("closed_at", DateTime(timezone=True)),
    Column("close_reason", String(40)),
    Column("microphone_released", Boolean(), nullable=False),
    Column("player_released", Boolean(), nullable=False),
    ForeignKeyConstraint(
        ["tenant_id", "thread_id"],
        ["threads.tenant_id", "threads.thread_id"],
        ondelete="CASCADE",
        name="fk_voice_sessions_thread_tenant",
    ),
)
Index(
    "ix_voice_sessions_tenant_thread_created_at",
    voice_sessions.c.tenant_id,
    voice_sessions.c.thread_id,
    voice_sessions.c.created_at,
)
Index(
    "ix_voice_sessions_tenant_status",
    voice_sessions.c.tenant_id,
    voice_sessions.c.status,
)


voice_resume_tokens = Table(
    "voice_resume_tokens",
    metadata,
    Column("tenant_id", String(120), primary_key=True),
    Column("resume_token_jti", String(200), primary_key=True),
    Column("session_id", String(120), nullable=False),
    Column("user_id", String(120), nullable=False),
    Column("session_generation", Integer(), nullable=False),
    Column("issued_at", DateTime(timezone=True), nullable=False),
    Column("expires_at", DateTime(timezone=True), nullable=False),
    Column("resume_token_consumed_at", DateTime(timezone=True)),
    ForeignKeyConstraint(
        ["tenant_id", "session_id"],
        ["voice_sessions.tenant_id", "voice_sessions.session_id"],
        ondelete="CASCADE",
        name="fk_voice_resume_tokens_session_tenant",
    ),
)
Index(
    "ix_voice_resume_tokens_tenant_session_generation",
    voice_resume_tokens.c.tenant_id,
    voice_resume_tokens.c.session_id,
    voice_resume_tokens.c.session_generation,
)


voice_turns = Table(
    "voice_turns",
    metadata,
    Column("tenant_id", String(120), primary_key=True),
    Column("session_id", String(120), primary_key=True),
    Column("turn_id", String(120), primary_key=True),
    Column("transcript_id", String(200), nullable=False),
    Column("request_id", String(160), nullable=False),
    Column("execution_id", String(120)),
    Column("response_envelope_id", String(120)),
    Column("status", String(20), nullable=False),
    Column("user_transcript", Text(), nullable=False),
    Column("assistant_content", Text()),
    Column("assistant_content_sha256", String(64)),
    Column("tts_input_sha256", String(64)),
    Column("audio_status", String(20), nullable=False),
    Column("spoken_content_complete", Boolean(), nullable=False),
    Column("canonical_text_preserved", Boolean(), nullable=False),
    Column("response_payload_json", Text()),
    Column("error_code", String(120)),
    Column("error_message", Text()),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("completed_at", DateTime(timezone=True)),
    ForeignKeyConstraint(
        ["tenant_id", "session_id"],
        ["voice_sessions.tenant_id", "voice_sessions.session_id"],
        ondelete="CASCADE",
        name="fk_voice_turns_session_tenant",
    ),
    UniqueConstraint(
        "tenant_id",
        "session_id",
        "transcript_id",
        name="uq_voice_turns_tenant_session_transcript",
    ),
    UniqueConstraint(
        "tenant_id",
        "execution_id",
        "response_envelope_id",
        name="uq_voice_turns_tenant_execution_response",
    ),
)
Index(
    "ix_voice_turns_tenant_session_created_at",
    voice_turns.c.tenant_id,
    voice_turns.c.session_id,
    voice_turns.c.created_at,
)


voice_events = Table(
    "voice_events",
    metadata,
    Column("tenant_id", String(120), primary_key=True),
    Column("event_id", String(160), primary_key=True),
    Column("canonical_event_id", String(160), nullable=False),
    Column("session_id", String(120), nullable=False),
    Column("canonical_sequence", Integer(), nullable=False),
    Column("source", String(40), nullable=False),
    Column("source_event_key", String(200), nullable=False),
    Column("source_delivery_id", String(200), nullable=False),
    Column("semantic_operation_id", String(200), nullable=False),
    Column("event_type", String(200), nullable=False),
    Column("session_generation", Integer(), nullable=False),
    Column("source_sequence", Integer()),
    Column("source_connection_id", String(200)),
    Column("turn_id", String(120)),
    Column("execution_id", String(120)),
    Column("payload_json", Text(), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    ForeignKeyConstraint(
        ["tenant_id", "session_id"],
        ["voice_sessions.tenant_id", "voice_sessions.session_id"],
        ondelete="CASCADE",
        name="fk_voice_events_session_tenant",
    ),
    UniqueConstraint(
        "tenant_id",
        "session_id",
        "canonical_sequence",
        name="uq_voice_events_tenant_session_sequence",
    ),
    UniqueConstraint(
        "tenant_id",
        "canonical_event_id",
        name="uq_voice_events_tenant_canonical_event",
    ),
    UniqueConstraint(
        "tenant_id",
        "session_id",
        "source",
        "source_delivery_id",
        name="uq_voice_events_source_delivery",
    ),
    UniqueConstraint(
        "tenant_id",
        "session_id",
        "source",
        "semantic_operation_id",
        name="uq_voice_events_semantic_operation",
    ),
)
Index(
    "ix_voice_events_tenant_session_sequence",
    voice_events.c.tenant_id,
    voice_events.c.session_id,
    voice_events.c.canonical_sequence,
)


def normalize_database_url(url: str) -> str:
    normalized = url.strip()
    if normalized.startswith("postgresql://"):
        return (
            "postgresql+psycopg://"
            + normalized.removeprefix("postgresql://")
        )
    if normalized.startswith("postgres://"):
        return (
            "postgresql+psycopg://"
            + normalized.removeprefix("postgres://")
        )
    return normalized


def database_driver_descriptor(url: str) -> dict[str, str]:
    parsed = make_url(normalize_database_url(url))
    return {
        "drivername": parsed.drivername,
        "backend": parsed.get_backend_name(),
        "driver": parsed.get_driver_name(),
    }


def create_database_engine(url: str, *, echo: bool = False) -> Engine:
    normalized_url = normalize_database_url(url)
    kwargs: dict[str, object] = {
        "pool_pre_ping": True,
        "echo": echo,
    }
    if normalized_url.startswith("sqlite") and ":memory:" in normalized_url:
        kwargs["connect_args"] = {"check_same_thread": False}
        kwargs["poolclass"] = StaticPool
    return create_engine(normalized_url, **kwargs)

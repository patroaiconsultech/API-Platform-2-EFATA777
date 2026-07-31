from sqlalchemy import (
    Column,
    DateTime,
    ForeignKeyConstraint,
    Index,
    MetaData,
    String,
    Table,
    Text,
    UniqueConstraint,
    create_engine,
)
from sqlalchemy.engine import Engine
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


def create_database_engine(url: str, *, echo: bool = False) -> Engine:
    kwargs: dict[str, object] = {
        "pool_pre_ping": True,
        "echo": echo,
    }
    if url.startswith("sqlite") and ":memory:" in url:
        kwargs["connect_args"] = {"check_same_thread": False}
        kwargs["poolclass"] = StaticPool
    return create_engine(url, **kwargs)

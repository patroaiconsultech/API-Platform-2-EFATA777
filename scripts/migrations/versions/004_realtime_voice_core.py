from alembic import op
import sqlalchemy as sa

revision = "004_realtime_voice_core"
down_revision = "003_premium_execution_control"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "voice_sessions",
        sa.Column("tenant_id", sa.String(120), nullable=False),
        sa.Column("session_id", sa.String(120), nullable=False),
        sa.Column("thread_id", sa.String(120), nullable=False),
        sa.Column("user_id", sa.String(120), nullable=False),
        sa.Column("requested_agent", sa.String(120), nullable=False),
        sa.Column("resolved_agent", sa.String(120), nullable=False),
        sa.Column("turn_owner", sa.String(120), nullable=False),
        sa.Column("ownership_locked", sa.Boolean(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("session_generation", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(80), nullable=False),
        sa.Column("provider_call_id", sa.String(200)),
        sa.Column("source_connection_id", sa.String(200)),
        sa.Column("last_canonical_sequence", sa.Integer(), nullable=False),
        sa.Column("reconnect_attempts", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("connected_at", sa.DateTime(timezone=True)),
        sa.Column("closed_at", sa.DateTime(timezone=True)),
        sa.Column("close_reason", sa.String(40)),
        sa.Column("microphone_released", sa.Boolean(), nullable=False),
        sa.Column("player_released", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(
            ["tenant_id", "thread_id"],
            ["threads.tenant_id", "threads.thread_id"],
            name="fk_voice_sessions_thread_tenant",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "tenant_id",
            "session_id",
            name="pk_voice_sessions",
        ),
    )
    op.create_index(
        "ix_voice_sessions_tenant_thread_created_at",
        "voice_sessions",
        ["tenant_id", "thread_id", "created_at"],
    )
    op.create_index(
        "ix_voice_sessions_tenant_status",
        "voice_sessions",
        ["tenant_id", "status"],
    )

    op.create_table(
        "voice_turns",
        sa.Column("tenant_id", sa.String(120), nullable=False),
        sa.Column("session_id", sa.String(120), nullable=False),
        sa.Column("turn_id", sa.String(120), nullable=False),
        sa.Column("transcript_id", sa.String(200), nullable=False),
        sa.Column("request_id", sa.String(160), nullable=False),
        sa.Column("execution_id", sa.String(120)),
        sa.Column("response_envelope_id", sa.String(120)),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("user_transcript", sa.Text(), nullable=False),
        sa.Column("assistant_content", sa.Text()),
        sa.Column("assistant_content_sha256", sa.String(64)),
        sa.Column("tts_input_sha256", sa.String(64)),
        sa.Column("audio_status", sa.String(20), nullable=False),
        sa.Column("spoken_content_complete", sa.Boolean(), nullable=False),
        sa.Column("canonical_text_preserved", sa.Boolean(), nullable=False),
        sa.Column("response_payload_json", sa.Text()),
        sa.Column("error_code", sa.String(120)),
        sa.Column("error_message", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(
            ["tenant_id", "session_id"],
            ["voice_sessions.tenant_id", "voice_sessions.session_id"],
            name="fk_voice_turns_session_tenant",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "tenant_id",
            "session_id",
            "turn_id",
            name="pk_voice_turns",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "session_id",
            "transcript_id",
            name="uq_voice_turns_tenant_session_transcript",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "execution_id",
            "response_envelope_id",
            name="uq_voice_turns_tenant_execution_response",
        ),
    )
    op.create_index(
        "ix_voice_turns_tenant_session_created_at",
        "voice_turns",
        ["tenant_id", "session_id", "created_at"],
    )

    op.create_table(
        "voice_events",
        sa.Column("tenant_id", sa.String(120), nullable=False),
        sa.Column("event_id", sa.String(160), nullable=False),
        sa.Column("session_id", sa.String(120), nullable=False),
        sa.Column("canonical_sequence", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(40), nullable=False),
        sa.Column("source_event_key", sa.String(200), nullable=False),
        sa.Column("event_type", sa.String(200), nullable=False),
        sa.Column("session_generation", sa.Integer(), nullable=False),
        sa.Column("source_sequence", sa.Integer()),
        sa.Column("source_connection_id", sa.String(200)),
        sa.Column("turn_id", sa.String(120)),
        sa.Column("execution_id", sa.String(120)),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["tenant_id", "session_id"],
            ["voice_sessions.tenant_id", "voice_sessions.session_id"],
            name="fk_voice_events_session_tenant",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "tenant_id",
            "event_id",
            name="pk_voice_events",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "session_id",
            "canonical_sequence",
            name="uq_voice_events_tenant_session_sequence",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "session_id",
            "source",
            "source_event_key",
            name="uq_voice_events_semantic_dedupe",
        ),
    )
    op.create_index(
        "ix_voice_events_tenant_session_sequence",
        "voice_events",
        ["tenant_id", "session_id", "canonical_sequence"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_voice_events_tenant_session_sequence",
        table_name="voice_events",
    )
    op.drop_table("voice_events")
    op.drop_index(
        "ix_voice_turns_tenant_session_created_at",
        table_name="voice_turns",
    )
    op.drop_table("voice_turns")
    op.drop_index(
        "ix_voice_sessions_tenant_status",
        table_name="voice_sessions",
    )
    op.drop_index(
        "ix_voice_sessions_tenant_thread_created_at",
        table_name="voice_sessions",
    )
    op.drop_table("voice_sessions")

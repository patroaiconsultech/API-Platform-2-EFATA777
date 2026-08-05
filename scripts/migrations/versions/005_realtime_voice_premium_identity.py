from alembic import op
import sqlalchemy as sa


revision = "005_realtime_voice_premium_identity"
down_revision = "004_realtime_voice_core"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "voice_resume_tokens",
        sa.Column("tenant_id", sa.String(120), nullable=False),
        sa.Column("resume_token_jti", sa.String(200), nullable=False),
        sa.Column("session_id", sa.String(120), nullable=False),
        sa.Column("user_id", sa.String(120), nullable=False),
        sa.Column("session_generation", sa.Integer(), nullable=False),
        sa.Column(
            "issued_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "expires_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "resume_token_consumed_at",
            sa.DateTime(timezone=True),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "session_id"],
            ["voice_sessions.tenant_id", "voice_sessions.session_id"],
            name="fk_voice_resume_tokens_session_tenant",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "tenant_id",
            "resume_token_jti",
            name="pk_voice_resume_tokens",
        ),
    )
    op.create_index(
        "ix_voice_resume_tokens_tenant_session_generation",
        "voice_resume_tokens",
        ["tenant_id", "session_id", "session_generation"],
    )

    op.add_column(
        "voice_events",
        sa.Column("canonical_event_id", sa.String(160), nullable=True),
    )
    op.add_column(
        "voice_events",
        sa.Column("source_delivery_id", sa.String(200), nullable=True),
    )
    op.add_column(
        "voice_events",
        sa.Column("semantic_operation_id", sa.String(200), nullable=True),
    )

    op.execute(
        """
        UPDATE voice_events
        SET canonical_event_id = event_id,
            source_delivery_id = source_event_key,
            semantic_operation_id = source_event_key
        """
    )

    op.alter_column(
        "voice_events",
        "canonical_event_id",
        existing_type=sa.String(160),
        nullable=False,
    )
    op.alter_column(
        "voice_events",
        "source_delivery_id",
        existing_type=sa.String(200),
        nullable=False,
    )
    op.alter_column(
        "voice_events",
        "semantic_operation_id",
        existing_type=sa.String(200),
        nullable=False,
    )

    op.drop_constraint(
        "uq_voice_events_semantic_dedupe",
        "voice_events",
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_voice_events_tenant_canonical_event",
        "voice_events",
        ["tenant_id", "canonical_event_id"],
    )
    op.create_unique_constraint(
        "uq_voice_events_source_delivery",
        "voice_events",
        [
            "tenant_id",
            "session_id",
            "source",
            "source_delivery_id",
        ],
    )
    op.create_unique_constraint(
        "uq_voice_events_semantic_operation",
        "voice_events",
        [
            "tenant_id",
            "session_id",
            "source",
            "semantic_operation_id",
        ],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_voice_events_semantic_operation",
        "voice_events",
        type_="unique",
    )
    op.drop_constraint(
        "uq_voice_events_source_delivery",
        "voice_events",
        type_="unique",
    )
    op.drop_constraint(
        "uq_voice_events_tenant_canonical_event",
        "voice_events",
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_voice_events_semantic_dedupe",
        "voice_events",
        ["tenant_id", "session_id", "source", "source_event_key"],
    )

    op.drop_column("voice_events", "semantic_operation_id")
    op.drop_column("voice_events", "source_delivery_id")
    op.drop_column("voice_events", "canonical_event_id")

    op.drop_index(
        "ix_voice_resume_tokens_tenant_session_generation",
        table_name="voice_resume_tokens",
    )
    op.drop_table("voice_resume_tokens")

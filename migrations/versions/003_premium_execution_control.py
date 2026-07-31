from alembic import op
import sqlalchemy as sa

revision = "003_premium_execution_control"
down_revision = "002_rc1_execution_idempotency"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "executions",
        sa.Column("lease_owner", sa.String(length=120), nullable=True),
    )
    op.add_column(
        "executions",
        sa.Column(
            "lease_expires_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.add_column(
        "executions",
        sa.Column(
            "heartbeat_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.execute(
        """
        UPDATE executions
        SET lease_owner = execution_id,
            heartbeat_at = started_at,
            lease_expires_at = started_at + INTERVAL '60 seconds'
        """
    )
    op.alter_column(
        "executions",
        "lease_owner",
        existing_type=sa.String(length=120),
        nullable=False,
    )
    op.alter_column(
        "executions",
        "lease_expires_at",
        existing_type=sa.DateTime(timezone=True),
        nullable=False,
    )
    op.alter_column(
        "executions",
        "heartbeat_at",
        existing_type=sa.DateTime(timezone=True),
        nullable=False,
    )
    op.create_index(
        "ix_executions_lease_expiry",
        "executions",
        ["tenant_id", "lease_expires_at"],
        unique=False,
    )

    op.create_table(
        "recovery_decisions",
        sa.Column("tenant_id", sa.String(length=120), nullable=False),
        sa.Column("decision_id", sa.String(length=120), nullable=False),
        sa.Column("request_id", sa.String(length=160), nullable=False),
        sa.Column("execution_id", sa.String(length=120), nullable=False),
        sa.Column("actor_id", sa.String(length=120), nullable=False),
        sa.Column("decision", sa.String(length=20), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "request_id"],
            ["executions.tenant_id", "executions.request_id"],
            name="fk_recovery_decisions_execution_request",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "tenant_id",
            "decision_id",
            name="pk_recovery_decisions",
        ),
    )
    op.create_index(
        "ix_recovery_decisions_request",
        "recovery_decisions",
        ["tenant_id", "request_id", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_recovery_decisions_request",
        table_name="recovery_decisions",
    )
    op.drop_table("recovery_decisions")
    op.drop_index(
        "ix_executions_lease_expiry",
        table_name="executions",
    )
    op.drop_column("executions", "heartbeat_at")
    op.drop_column("executions", "lease_expires_at")
    op.drop_column("executions", "lease_owner")

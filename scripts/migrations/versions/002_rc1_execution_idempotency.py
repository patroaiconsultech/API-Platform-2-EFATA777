from alembic import op
import sqlalchemy as sa

revision = "002_rc1_execution_idempotency"
down_revision = "001_rc1_core_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "messages",
        "request_id",
        existing_type=sa.String(length=120),
        type_=sa.String(length=160),
        existing_nullable=True,
    )
    op.alter_column(
        "messages",
        "display_name",
        existing_type=sa.String(length=120),
        type_=sa.String(length=160),
        existing_nullable=True,
    )
    op.add_column(
        "messages",
        sa.Column("error_code", sa.String(length=120), nullable=True),
    )
    op.add_column(
        "messages",
        sa.Column("error_message", sa.Text(), nullable=True),
    )
    op.create_unique_constraint(
        "uq_messages_tenant_execution_role",
        "messages",
        ["tenant_id", "execution_id", "role"],
    )

    op.create_table(
        "executions",
        sa.Column("tenant_id", sa.String(length=120), nullable=False),
        sa.Column("request_id", sa.String(length=160), nullable=False),
        sa.Column("execution_id", sa.String(length=120), nullable=False),
        sa.Column("thread_id", sa.String(length=120), nullable=False),
        sa.Column("user_id", sa.String(length=120), nullable=False),
        sa.Column("requested_agent", sa.String(length=120), nullable=False),
        sa.Column("resolved_agent", sa.String(length=120), nullable=False),
        sa.Column("turn_owner", sa.String(length=120), nullable=False),
        sa.Column("display_name", sa.String(length=160), nullable=False),
        sa.Column("route_family", sa.String(length=120), nullable=False),
        sa.Column(
            "request_fingerprint_sha256",
            sa.String(length=64),
            nullable=False,
        ),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("error_code", sa.String(length=120), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("user_message_id", sa.String(length=120), nullable=True),
        sa.Column(
            "assistant_message_id",
            sa.String(length=120),
            nullable=True,
        ),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "completed_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "thread_id"],
            ["threads.tenant_id", "threads.thread_id"],
            name="fk_executions_thread_tenant",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "tenant_id",
            "request_id",
            name="pk_executions",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "execution_id",
            name="uq_executions_tenant_execution",
        ),
    )
    op.create_index(
        "ix_executions_tenant_status",
        "executions",
        ["tenant_id", "status"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_executions_tenant_status",
        table_name="executions",
    )
    op.drop_table("executions")
    op.drop_constraint(
        "uq_messages_tenant_execution_role",
        "messages",
        type_="unique",
    )
    op.drop_column("messages", "error_message")
    op.drop_column("messages", "error_code")
    op.alter_column(
        "messages",
        "display_name",
        existing_type=sa.String(length=160),
        type_=sa.String(length=120),
        existing_nullable=True,
    )
    op.alter_column(
        "messages",
        "request_id",
        existing_type=sa.String(length=160),
        type_=sa.String(length=120),
        existing_nullable=True,
    )

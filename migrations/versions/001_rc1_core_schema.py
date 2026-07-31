from alembic import op
import sqlalchemy as sa

revision = "001_rc1_core_schema"
down_revision = None
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.create_table(
        "threads",
        sa.Column("tenant_id", sa.String(120), nullable=False),
        sa.Column("thread_id", sa.String(120), nullable=False),
        sa.Column("created_by", sa.String(120), nullable=False),
        sa.Column("title", sa.String(160), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("tenant_id","thread_id", name="pk_threads"),
    )
    op.create_index("ix_threads_tenant_created_at","threads",["tenant_id","created_at"])
    op.create_table(
        "messages",
        sa.Column("tenant_id", sa.String(120), nullable=False),
        sa.Column("message_id", sa.String(120), nullable=False),
        sa.Column("thread_id", sa.String(120), nullable=False),
        sa.Column("user_id", sa.String(120), nullable=False),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("agent_id", sa.String(120)),
        sa.Column("agent_name", sa.String(120)),
        sa.Column("display_name", sa.String(120)),
        sa.Column("final_speaker", sa.String(120)),
        sa.Column("turn_owner", sa.String(120)),
        sa.Column("request_id", sa.String(120)),
        sa.Column("execution_id", sa.String(120)),
        sa.Column("route_family", sa.String(120)),
        sa.Column("status", sa.String(20)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["tenant_id","thread_id"], ["threads.tenant_id","threads.thread_id"],
            name="fk_messages_thread_tenant", ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("tenant_id","message_id", name="pk_messages"),
    )
    op.create_index("ix_messages_tenant_thread_created_at","messages",["tenant_id","thread_id","created_at"])
    op.create_index("ix_messages_execution_id","messages",["execution_id"])

def downgrade() -> None:
    op.drop_index("ix_messages_execution_id", table_name="messages")
    op.drop_index("ix_messages_tenant_thread_created_at", table_name="messages")
    op.drop_table("messages")
    op.drop_index("ix_threads_tenant_created_at", table_name="threads")
    op.drop_table("threads")

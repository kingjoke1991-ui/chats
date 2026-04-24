"""chat and model gateway schema"""

from __future__ import annotations

import json

from alembic import op
import sqlalchemy as sa


revision = "20260418_0002"
down_revision = "20260418_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "model_nodes",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("code", sa.String(length=64), nullable=False, unique=True),
        sa.Column("provider_type", sa.String(length=32), nullable=False),
        sa.Column("provider_code", sa.String(length=64), nullable=False),
        sa.Column("base_url", sa.Text(), nullable=False),
        sa.Column("api_key_encrypted", sa.Text(), nullable=True),
        sa.Column("model_name", sa.String(length=128), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="healthy"),
        sa.Column("weight", sa.Integer(), nullable=False, server_default="100"),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="100"),
        sa.Column("max_parallel_requests", sa.Integer(), nullable=False, server_default="100"),
        sa.Column("current_parallel_requests", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("avg_ttft_ms", sa.Integer(), nullable=True),
        sa.Column("avg_tps", sa.Numeric(10, 2), nullable=True),
        sa.Column("capability_json", sa.JSON(), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
        sa.Column("last_healthcheck_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_healthy_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_model_nodes_provider_code", "model_nodes", ["provider_code"])
    op.create_index("ix_model_nodes_status", "model_nodes", ["status"])

    op.create_table(
        "conversations",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("pinned", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("archived", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("latest_model", sa.String(length=128), nullable=True),
        sa.Column("latest_message_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("message_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
    )
    op.create_index("ix_conversations_user_id", "conversations", ["user_id"])
    op.create_index("ix_conversations_archived", "conversations", ["archived"])
    op.create_index("ix_conversations_latest_message_at", "conversations", ["latest_message_at"])
    op.create_index("ix_conversations_deleted_at", "conversations", ["deleted_at"])

    op.create_table(
        "messages",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("conversation_id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("parent_message_id", sa.String(length=36), nullable=True),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column("content_text", sa.Text(), nullable=False),
        sa.Column("content_json", sa.JSON(), nullable=True),
        sa.Column("model", sa.String(length=128), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("prompt_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("completion_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("finish_reason", sa.String(length=64), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("request_id", sa.String(length=128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"]),
        sa.ForeignKeyConstraint(["parent_message_id"], ["messages.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
    )
    op.create_index("ix_messages_conversation_id", "messages", ["conversation_id"])
    op.create_index("ix_messages_user_id", "messages", ["user_id"])
    op.create_index("ix_messages_request_id", "messages", ["request_id"])

    model_nodes_table = sa.table(
        "model_nodes",
        sa.column("id", sa.String()),
        sa.column("code", sa.String()),
        sa.column("provider_type", sa.String()),
        sa.column("provider_code", sa.String()),
        sa.column("base_url", sa.Text()),
        sa.column("api_key_encrypted", sa.Text()),
        sa.column("model_name", sa.String()),
        sa.column("enabled", sa.Boolean()),
        sa.column("status", sa.String()),
        sa.column("weight", sa.Integer()),
        sa.column("priority", sa.Integer()),
        sa.column("max_parallel_requests", sa.Integer()),
        sa.column("current_parallel_requests", sa.Integer()),
        sa.column("capability_json", sa.JSON()),
        sa.column("metadata_json", sa.JSON()),
    )
    op.bulk_insert(
        model_nodes_table,
        [
            {
                "id": "node-gemma-primary-0001",
                "code": "gemma-primary",
                "provider_type": "openai_compat",
                "provider_code": "gemma",
                "base_url": "https://sd3.202574.xyz/v1",
                "api_key_encrypted": None,
                "model_name": "gemma-4-31B-Mystery-Fine-Tune-HERETIC-UNCENSORED-INSTRUCT-Q4_K_S.gguf",
                "enabled": True,
                "status": "healthy",
                "weight": 100,
                "priority": 100,
                "max_parallel_requests": 100,
                "current_parallel_requests": 0,
                "capability_json": {
                    "model_aliases": [
                        "gemma/gemma-4-31B-Mystery-Fine-Tune-HERETIC-UNCENSORED-INSTRUCT-Q4_K_S.gguf",
                        "gemma-4-31B-Mystery-Fine-Tune-HERETIC-UNCENSORED-INSTRUCT-Q4_K_S.gguf",
                    ]
                },
                "metadata_json": {"source": "models.md"},
            }
        ],
    )

    free_models = json.dumps(
        [
            "gemma/gemma-4-31B-Mystery-Fine-Tune-HERETIC-UNCENSORED-INSTRUCT-Q4_K_S.gguf",
            "gemma-4-31B-Mystery-Fine-Tune-HERETIC-UNCENSORED-INSTRUCT-Q4_K_S.gguf",
        ]
    )
    bind = op.get_bind()
    bind.execute(
        sa.text("UPDATE plans SET allowed_models_json = CAST(:models AS JSON) WHERE code IN ('free', 'pro', 'ultra')"),
        {"models": free_models},
    )


def downgrade() -> None:
    op.drop_index("ix_messages_request_id", table_name="messages")
    op.drop_index("ix_messages_user_id", table_name="messages")
    op.drop_index("ix_messages_conversation_id", table_name="messages")
    op.drop_table("messages")
    op.drop_index("ix_conversations_deleted_at", table_name="conversations")
    op.drop_index("ix_conversations_latest_message_at", table_name="conversations")
    op.drop_index("ix_conversations_archived", table_name="conversations")
    op.drop_index("ix_conversations_user_id", table_name="conversations")
    op.drop_table("conversations")
    op.drop_index("ix_model_nodes_status", table_name="model_nodes")
    op.drop_index("ix_model_nodes_provider_code", table_name="model_nodes")
    op.drop_table("model_nodes")

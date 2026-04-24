"""initial schema"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260418_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("phone", sa.String(length=32), nullable=True),
        sa.Column("username", sa.String(length=64), nullable=True),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("email_verified", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("avatar_url", sa.Text(), nullable=True),
        sa.Column("timezone", sa.String(length=64), nullable=True),
        sa.Column("locale", sa.String(length=16), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("email"),
        sa.UniqueConstraint("phone"),
        sa.UniqueConstraint("username"),
    )
    op.create_index("ix_users_status", "users", ["status"])
    op.create_index("ix_users_email", "users", ["email"])

    op.create_table(
        "plans",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("code", sa.String(length=64), nullable=False, unique=True),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("monthly_price_cents", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(length=16), nullable=False),
        sa.Column("monthly_soft_token_limit", sa.BigInteger(), nullable=False),
        sa.Column("daily_soft_token_limit", sa.BigInteger(), nullable=False),
        sa.Column("max_concurrent_requests", sa.Integer(), nullable=False),
        sa.Column("max_input_tokens", sa.Integer(), nullable=False),
        sa.Column("max_output_tokens", sa.Integer(), nullable=False),
        sa.Column("max_context_tokens", sa.Integer(), nullable=False),
        sa.Column("priority_level", sa.Integer(), nullable=False),
        sa.Column("allowed_models_json", sa.JSON(), nullable=False),
        sa.Column("features_json", sa.JSON(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    op.create_table(
        "auth_sessions",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("refresh_token_hash", sa.String(length=255), nullable=False),
        sa.Column("device_id", sa.String(length=128), nullable=True),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.Column("ip_address", sa.String(length=64), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
    )
    op.create_index("ix_auth_sessions_user_id", "auth_sessions", ["user_id"])
    op.create_index("ix_auth_sessions_status", "auth_sessions", ["status"])
    op.create_index("ix_auth_sessions_expires_at", "auth_sessions", ["expires_at"])

    op.create_table(
        "subscriptions",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("plan_id", sa.String(length=36), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("provider_customer_id", sa.String(length=255), nullable=True),
        sa.Column("provider_subscription_id", sa.String(length=255), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("start_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("cancel_at_period_end", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("canceled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("trial_end_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["plan_id"], ["plans.id"]),
        sa.UniqueConstraint("provider", "provider_subscription_id"),
    )
    op.create_index("ix_subscriptions_user_id", "subscriptions", ["user_id"])
    op.create_index("ix_subscriptions_status", "subscriptions", ["status"])
    op.create_index("ix_subscriptions_end_at", "subscriptions", ["end_at"])

    plans_table = sa.table(
        "plans",
        sa.column("id", sa.String()),
        sa.column("code", sa.String()),
        sa.column("name", sa.String()),
        sa.column("monthly_price_cents", sa.Integer()),
        sa.column("currency", sa.String()),
        sa.column("monthly_soft_token_limit", sa.BigInteger()),
        sa.column("daily_soft_token_limit", sa.BigInteger()),
        sa.column("max_concurrent_requests", sa.Integer()),
        sa.column("max_input_tokens", sa.Integer()),
        sa.column("max_output_tokens", sa.Integer()),
        sa.column("max_context_tokens", sa.Integer()),
        sa.column("priority_level", sa.Integer()),
        sa.column("allowed_models_json", sa.JSON()),
        sa.column("features_json", sa.JSON()),
        sa.column("is_active", sa.Boolean()),
    )

    op.bulk_insert(
        plans_table,
        [
            {
                "id": "plan-free-0001",
                "code": "free",
                "name": "Free",
                "monthly_price_cents": 0,
                "currency": "USD",
                "monthly_soft_token_limit": 2_000_000,
                "daily_soft_token_limit": 100_000,
                "max_concurrent_requests": 1,
                "max_input_tokens": 16000,
                "max_output_tokens": 2048,
                "max_context_tokens": 16000,
                "priority_level": 10,
                "allowed_models_json": ["gpt-4o-mini-like"],
                "features_json": {"stream": True},
                "is_active": True,
            },
            {
                "id": "plan-pro-0001",
                "code": "pro",
                "name": "Pro",
                "monthly_price_cents": 1999,
                "currency": "USD",
                "monthly_soft_token_limit": 20_000_000,
                "daily_soft_token_limit": 1_000_000,
                "max_concurrent_requests": 2,
                "max_input_tokens": 64000,
                "max_output_tokens": 4096,
                "max_context_tokens": 64000,
                "priority_level": 50,
                "allowed_models_json": ["gpt-4o-mini-like", "gpt-4.1-like"],
                "features_json": {"stream": True, "priority_routing": True},
                "is_active": True,
            },
            {
                "id": "plan-ultra-0001",
                "code": "ultra",
                "name": "Ultra",
                "monthly_price_cents": 4999,
                "currency": "USD",
                "monthly_soft_token_limit": 100_000_000,
                "daily_soft_token_limit": 5_000_000,
                "max_concurrent_requests": 4,
                "max_input_tokens": 128000,
                "max_output_tokens": 8192,
                "max_context_tokens": 128000,
                "priority_level": 100,
                "allowed_models_json": ["gpt-4o-mini-like", "gpt-4.1-like", "gpt-4.1-max-like"],
                "features_json": {"stream": True, "priority_routing": True, "premium_models": True},
                "is_active": True,
            },
        ],
    )


def downgrade() -> None:
    op.drop_index("ix_subscriptions_end_at", table_name="subscriptions")
    op.drop_index("ix_subscriptions_status", table_name="subscriptions")
    op.drop_index("ix_subscriptions_user_id", table_name="subscriptions")
    op.drop_table("subscriptions")
    op.drop_index("ix_auth_sessions_expires_at", table_name="auth_sessions")
    op.drop_index("ix_auth_sessions_status", table_name="auth_sessions")
    op.drop_index("ix_auth_sessions_user_id", table_name="auth_sessions")
    op.drop_table("auth_sessions")
    op.drop_table("plans")
    op.drop_index("ix_users_email", table_name="users")
    op.drop_index("ix_users_status", table_name="users")
    op.drop_table("users")

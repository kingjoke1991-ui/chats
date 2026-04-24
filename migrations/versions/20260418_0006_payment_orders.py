"""payment orders"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260418_0006"
down_revision = "20260418_0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "payment_orders",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("plan_id", sa.String(length=36), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("merchant_order_id", sa.String(length=128), nullable=False),
        sa.Column("provider_trade_id", sa.String(length=128), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("amount_cents", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(length=16), nullable=False),
        sa.Column("checkout_url", sa.Text(), nullable=True),
        sa.Column("payment_token", sa.String(length=255), nullable=True),
        sa.Column("redirect_url", sa.Text(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("canceled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("provider_payload_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["plan_id"], ["plans.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.UniqueConstraint("merchant_order_id"),
        sa.UniqueConstraint("provider_trade_id"),
    )
    op.create_index("ix_payment_orders_user_id", "payment_orders", ["user_id"])
    op.create_index("ix_payment_orders_plan_id", "payment_orders", ["plan_id"])
    op.create_index("ix_payment_orders_provider", "payment_orders", ["provider"])
    op.create_index("ix_payment_orders_merchant_order_id", "payment_orders", ["merchant_order_id"])
    op.create_index("ix_payment_orders_provider_trade_id", "payment_orders", ["provider_trade_id"])
    op.create_index("ix_payment_orders_status", "payment_orders", ["status"])
    op.create_index("ix_payment_orders_expires_at", "payment_orders", ["expires_at"])


def downgrade() -> None:
    op.drop_index("ix_payment_orders_expires_at", table_name="payment_orders")
    op.drop_index("ix_payment_orders_status", table_name="payment_orders")
    op.drop_index("ix_payment_orders_provider_trade_id", table_name="payment_orders")
    op.drop_index("ix_payment_orders_merchant_order_id", table_name="payment_orders")
    op.drop_index("ix_payment_orders_provider", table_name="payment_orders")
    op.drop_index("ix_payment_orders_plan_id", table_name="payment_orders")
    op.drop_index("ix_payment_orders_user_id", table_name="payment_orders")
    op.drop_table("payment_orders")

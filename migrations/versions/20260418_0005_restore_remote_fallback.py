"""restore remote fallback node"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260418_0005"
down_revision = "20260418_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    bind.execute(
        sa.text(
            "UPDATE model_nodes SET enabled = true, priority = 100, weight = 100 "
            "WHERE code = 'gemma-primary'"
        )
    )
    bind.execute(
        sa.text(
            "UPDATE model_nodes SET enabled = true, priority = 200, weight = 200 "
            "WHERE code = 'gemma-e2b-local'"
        )
    )


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(
        sa.text(
            "UPDATE model_nodes SET enabled = false, priority = 10, weight = 10 "
            "WHERE code = 'gemma-primary'"
        )
    )

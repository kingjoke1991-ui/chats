"""add local gemma-4-e2b model node and update plan allowed models"""

from __future__ import annotations

import json

from alembic import op
import sqlalchemy as sa


revision = "20260418_0004"
down_revision = "20260418_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
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

    # 添加本地 gemma-4-e2b 节点
    op.bulk_insert(
        model_nodes_table,
        [
            {
                "id": "node-gemma-e2b-local-0001",
                "code": "gemma-e2b-local",
                "provider_type": "openai_compat",
                "provider_code": "gemma",
                "base_url": "http://host.docker.internal:11435/v1",
                "api_key_encrypted": None,
                "model_name": "gemma-4-e2b-q6_k_p",
                "enabled": True,
                "status": "healthy",
                "weight": 200,
                "priority": 200,
                "max_parallel_requests": 1,
                "current_parallel_requests": 0,
                "capability_json": {
                    "model_aliases": [
                        "gemma-4-e2b-q6_k_p",
                        "gemma-4-e2b",
                    ]
                },
                "metadata_json": {"source": "mode.md", "type": "local-llama-server"},
            }
        ],
    )

    # 将旧的 sd3 节点降级（关闭 + 降低优先级）
    bind = op.get_bind()
    bind.execute(
        sa.text(
            "UPDATE model_nodes SET enabled = false, status = 'unhealthy', priority = 10, weight = 10 "
            "WHERE code = 'gemma-primary'"
        )
    )

    # 更新所有套餐的 allowed_models_json，添加本地 e2b 模型
    all_models = json.dumps([
        "gemma-4-e2b-q6_k_p",
        "gemma-4-e2b",
        "gemma/gemma-4-31B-Mystery-Fine-Tune-HERETIC-UNCENSORED-INSTRUCT-Q4_K_S.gguf",
        "gemma-4-31B-Mystery-Fine-Tune-HERETIC-UNCENSORED-INSTRUCT-Q4_K_S.gguf",
    ])
    bind.execute(
        sa.text("UPDATE plans SET allowed_models_json = CAST(:models AS JSON) WHERE code IN ('free', 'pro', 'ultra')"),
        {"models": all_models},
    )


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(sa.text("DELETE FROM model_nodes WHERE code = 'gemma-e2b-local'"))
    bind.execute(
        sa.text(
            "UPDATE model_nodes SET enabled = true, status = 'healthy', priority = 100, weight = 100 "
            "WHERE code = 'gemma-primary'"
        )
    )
    old_models = json.dumps([
        "gemma/gemma-4-31B-Mystery-Fine-Tune-HERETIC-UNCENSORED-INSTRUCT-Q4_K_S.gguf",
        "gemma-4-31B-Mystery-Fine-Tune-HERETIC-UNCENSORED-INSTRUCT-Q4_K_S.gguf",
    ])
    bind.execute(
        sa.text("UPDATE plans SET allowed_models_json = CAST(:models AS JSON) WHERE code IN ('free', 'pro', 'ultra')"),
        {"models": old_models},
    )

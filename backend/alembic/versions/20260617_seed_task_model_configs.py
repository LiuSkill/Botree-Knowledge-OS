"""seed task model configs

Revision ID: 20260617_seed_task_model_configs
Revises: 20260617_expand_chat_trace_longtext
Create Date: 2026-06-17
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op

revision: str = "20260617_seed_task_model_configs"
down_revision: str | None = "20260617_expand_chat_trace_longtext"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TASK_MODEL_DEFAULTS = (
    ("intent", "qwen3.5-flash", "llm"),
    ("planner", "qwen3.5-flash", "llm"),
    ("evidence_judge_fast", "qwen3.5-flash", "llm"),
    ("evidence_judge", "qwen3.5-plus", "llm"),
    ("answer_llm", "qwen3.5-plus", "llm"),
    ("vision_llm", "qwen3.5-plus", "vision_llm"),
    ("analysis_llm", "qwen3.7-max", "llm"),
)


def _model_configs_table() -> sa.TableClause:
    return sa.table(
        "model_configs",
        sa.column("provider", sa.String),
        sa.column("model_name", sa.String),
        sa.column("api_base", sa.String),
        sa.column("api_key", sa.String),
        sa.column("model_type", sa.String),
        sa.column("is_default", sa.Boolean),
        sa.column("enabled", sa.Boolean),
        sa.column("created_at", sa.DateTime),
        sa.column("updated_at", sa.DateTime),
    )


def _default_source_config(connection: sa.Connection, source_model_type: str) -> dict[str, str | None]:
    """复用已有默认模型的 provider/api_base，避免在迁移里固化密钥。"""

    source = connection.execute(
        sa.text(
            """
            SELECT provider, api_base
            FROM model_configs
            WHERE model_type = :model_type AND is_default = 1 AND enabled = 1
            ORDER BY id DESC
            LIMIT 1
            """
        ),
        {"model_type": source_model_type},
    ).mappings().first()
    if source:
        return {"provider": source["provider"], "api_base": source["api_base"]}

    llm_source = connection.execute(
        sa.text(
            """
            SELECT provider, api_base
            FROM model_configs
            WHERE model_type = 'llm' AND is_default = 1 AND enabled = 1
            ORDER BY id DESC
            LIMIT 1
            """
        )
    ).mappings().first()
    if llm_source:
        return {"provider": llm_source["provider"], "api_base": llm_source["api_base"]}
    return {"provider": "qwen_api", "api_base": None}


def _has_default(connection: sa.Connection, model_type: str) -> bool:
    return bool(
        connection.execute(
            sa.text(
                """
                SELECT 1
                FROM model_configs
                WHERE model_type = :model_type AND is_default = 1
                LIMIT 1
                """
            ),
            {"model_type": model_type},
        ).first()
    )


def upgrade() -> None:
    connection = op.get_bind()
    model_configs = _model_configs_table()
    now = datetime.now(UTC).replace(tzinfo=None)

    for model_type, model_name, source_model_type in TASK_MODEL_DEFAULTS:
        if _has_default(connection, model_type):
            continue
        source = _default_source_config(connection, source_model_type)
        connection.execute(
            model_configs.insert().values(
                provider=source["provider"],
                model_name=model_name,
                api_base=source["api_base"],
                api_key=None,
                model_type=model_type,
                is_default=True,
                enabled=True,
                created_at=now,
                updated_at=now,
            )
        )


def downgrade() -> None:
    # 数据迁移不自动删除，避免误删管理员后续修改过的模型配置。
    pass

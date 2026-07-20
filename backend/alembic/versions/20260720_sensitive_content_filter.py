"""add runtime sensitive content filter configuration

Revision ID: 20260720_sensitive_content_filter
Revises: 20260714_node_output_waste_fields
Create Date: 2026-07-20
"""

from collections.abc import Sequence
import json

import sqlalchemy as sa
from alembic import op

revision: str = "20260720_sensitive_content_filter"
down_revision: str | None = "20260714_node_output_waste_fields"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "sensitive_type",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("code", sa.String(100), nullable=False, unique=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("default_mask_text", sa.String(255), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_sensitive_type_code", "sensitive_type", ["code"], unique=True)
    op.create_table(
        "sensitive_filter_rule",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("code", sa.String(100), nullable=False, unique=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("sensitive_type_code", sa.String(100), sa.ForeignKey("sensitive_type.code"), nullable=False),
        sa.Column("match_type", sa.String(30), nullable=False),
        sa.Column("pattern", sa.Text(), nullable=False),
        sa.Column("context_keywords", sa.Text(), nullable=True),
        sa.Column("window_size", sa.Integer(), nullable=False, server_default="30"),
        sa.Column("mask_text", sa.String(255), nullable=True),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="100"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_sensitive_filter_rule_code", "sensitive_filter_rule", ["code"], unique=True)
    op.create_index("ix_sensitive_filter_rule_type", "sensitive_filter_rule", ["sensitive_type_code"])
    op.create_table(
        "role_sensitive_permission",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("role_id", sa.Integer(), sa.ForeignKey("roles.id", ondelete="CASCADE"), nullable=False),
        sa.Column("sensitive_type_code", sa.String(100), sa.ForeignKey("sensitive_type.code"), nullable=False),
        sa.Column("can_view", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("role_id", "sensitive_type_code", name="uq_role_sensitive_permission"),
    )
    op.create_index("ix_role_sensitive_permission_role", "role_sensitive_permission", ["role_id"])
    op.create_table(
        "sensitive_redaction_audit",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("role_ids", sa.Text(), nullable=False),
        sa.Column("message_id", sa.Integer(), nullable=True),
        sa.Column("chat_type", sa.String(30), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=True),
        sa.Column("redaction_types", sa.Text(), nullable=False),
        sa.Column("redaction_count", sa.Integer(), nullable=False),
        sa.Column("final_answer_redacted", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_sensitive_redaction_audit_user", "sensitive_redaction_audit", ["user_id"])

    types = sa.table("sensitive_type", sa.column("code"), sa.column("name"), sa.column("default_mask_text"), sa.column("enabled"))
    op.bulk_insert(types, [dict(code=code, name=name, default_mask_text=mask, enabled=True) for code, name, mask in _type_defaults()])
    rules = sa.table("sensitive_filter_rule", sa.column("code"), sa.column("name"), sa.column("sensitive_type_code"), sa.column("match_type"), sa.column("pattern"), sa.column("context_keywords"), sa.column("window_size"), sa.column("mask_text"), sa.column("priority"), sa.column("enabled"), sa.column("version"))
    op.bulk_insert(rules, _rule_defaults())
    connection = op.get_bind()
    type_codes = [item[0] for item in _type_defaults()]
    roles = connection.execute(sa.text("SELECT id, code FROM roles")).mappings().all()
    permissions = sa.table("role_sensitive_permission", sa.column("role_id"), sa.column("sensitive_type_code"), sa.column("can_view"))
    op.bulk_insert(permissions, [dict(role_id=role["id"], sensitive_type_code=code, can_view=role["code"] == "admin") for role in roles for code in type_codes])


def _type_defaults():
    return [("price", "报价信息", "[报价信息已隐藏]"), ("cost", "成本信息", "[成本信息已隐藏]"), ("gross_margin", "利润率信息", "[利润率信息已隐藏]"), ("contract_amount", "合同金额", "[合同金额已隐藏]"), ("payment_terms", "付款条件", "[付款条件已隐藏]"), ("supplier_price", "供应商报价", "[供应商报价已隐藏]"), ("business_strategy", "商务策略", "[商务策略信息已隐藏]"), ("financial_metric", "财务指标", "[财务指标已隐藏]")]


def _rule_defaults():
    amount = r"(?:(?:USD|CNY|RMB|￥|¥|\$)\s*\d+(?:\.\d+)?(?:\s*(?:万|亿|千)?\s*(?:元|人民币|美元|美金))?|\d+(?:\.\d+)?\s*(?:万|亿|千)?\s*(?:元|人民币|美元|美金))(?:\s*/\s*[\u4e00-\u9fa5A-Za-z]+)?"
    return [
        dict(code="supplier_price_rule", name="供应商报价识别", sensitive_type_code="supplier_price", match_type="keyword_window", pattern=amount, context_keywords=json.dumps(["供应商报价", "采购报价", "报价单", "供应商价格"], ensure_ascii=False), window_size=30, mask_text="[供应商报价已隐藏]", priority=5, enabled=True, version=1),
        dict(code="price_amount_rule", name="报价金额识别", sensitive_type_code="price", match_type="keyword_window", pattern=amount, context_keywords=json.dumps(["报价", "价格", "销售价", "销售单价", "合同价", "总价", "投标价", "中标价", "商务报价", "供货价"], ensure_ascii=False), window_size=30, mask_text="[报价信息已隐藏]", priority=10, enabled=True, version=1),
        dict(code="cost_amount_rule", name="成本金额识别", sensitive_type_code="cost", match_type="keyword_window", pattern=amount, context_keywords=json.dumps(["成本", "采购成本", "设备成本", "制造成本", "建设成本", "成本价", "采购价"], ensure_ascii=False), window_size=30, mask_text="[成本信息已隐藏]", priority=20, enabled=True, version=1),
        dict(code="gross_margin_rule", name="利润率识别", sensitive_type_code="gross_margin", match_type="keyword_window", pattern=r"\d+(?:\.\d+)?\s*%", context_keywords=json.dumps(["毛利率", "利润率", "毛利", "利润空间"], ensure_ascii=False), window_size=30, mask_text="[利润率信息已隐藏]", priority=30, enabled=True, version=1),
        dict(code="contract_amount_rule", name="合同金额识别", sensitive_type_code="contract_amount", match_type="keyword_window", pattern=amount, context_keywords=json.dumps(["合同金额", "合同总价", "合同价", "订单金额", "订单总价"], ensure_ascii=False), window_size=30, mask_text="[合同金额已隐藏]", priority=40, enabled=True, version=1),
        dict(code="payment_terms_rule", name="付款条件识别", sensitive_type_code="payment_terms", match_type="keyword", pattern=r"预付款|尾款|账期|付款条件|付款方式|验收后支付|合同款", context_keywords="[]", window_size=30, mask_text="[付款条件已隐藏]", priority=50, enabled=True, version=1),
        dict(code="business_strategy_rule", name="商务策略识别", sensitive_type_code="business_strategy", match_type="keyword", pattern=r"让利空间|价格底线|谈判空间|商务条件|底价", context_keywords="[]", window_size=30, mask_text="[商务策略信息已隐藏]", priority=60, enabled=True, version=1),
        dict(code="financial_metric_rule", name="财务指标识别", sensitive_type_code="financial_metric", match_type="keyword", pattern=r"\bIRR\b|\bNPV\b|投资回收期|现金流|财务回报率", context_keywords="[]", window_size=30, mask_text="[财务指标已隐藏]", priority=70, enabled=True, version=1),
    ]


def downgrade() -> None:
    op.drop_table("sensitive_redaction_audit")
    op.drop_table("role_sensitive_permission")
    op.drop_table("sensitive_filter_rule")
    op.drop_table("sensitive_type")

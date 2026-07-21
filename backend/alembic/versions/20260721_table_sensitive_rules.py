"""add table-aware sensitive filter rules

Revision ID: 20260721_table_sensitive_rules
Revises: 20260720_sensitive_content_filter
Create Date: 2026-07-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260721_table_sensitive_rules"
down_revision: str | None = "20260720_sensitive_content_filter"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    rules = sa.table(
        "sensitive_filter_rule",
        sa.column("code"), sa.column("name"), sa.column("sensitive_type_code"), sa.column("match_type"),
        sa.column("pattern"), sa.column("context_keywords"), sa.column("window_size"), sa.column("mask_text"),
        sa.column("priority"), sa.column("enabled"), sa.column("version"),
    )
    op.bulk_insert(rules, _table_rules())


def downgrade() -> None:
    codes = [item["code"] for item in _table_rules()]
    op.get_bind().execute(
        sa.text("DELETE FROM sensitive_filter_rule WHERE code IN :codes").bindparams(sa.bindparam("codes", expanding=True)),
        {"codes": codes},
    )


def _table_rules() -> list[dict]:
    defaults = [
        ("table_supplier_price_column_rule", "表格供应商报价列", "supplier_price", r"供应商报价|采购报价|供应商价格|供应商单价|供货价", "[供应商报价已隐藏]", 5),
        ("table_price_column_rule", "表格报价列", "price", r"报价|价格|单价|销售单价|总价|投标价|中标价|供货价", "[报价信息已隐藏]", 10),
        ("table_cost_column_rule", "表格成本列", "cost", r"成本|采购成本|设备成本|制造成本|建设成本|成本价|采购价", "[成本信息已隐藏]", 20),
        ("table_margin_column_rule", "表格利润率列", "gross_margin", r"毛利率|利润率|毛利|利润空间", "[利润率信息已隐藏]", 30),
        ("table_contract_amount_column_rule", "表格合同金额列", "contract_amount", r"合同金额|合同总价|合同价|订单金额|订单总价", "[合同金额已隐藏]", 40),
        ("table_payment_terms_column_rule", "表格付款条件列", "payment_terms", r"付款条件|付款方式|预付款|尾款|账期|验收后支付", "[付款条件已隐藏]", 50),
    ]
    return [
        dict(code=code, name=name, sensitive_type_code=type_code, match_type="table_column", pattern=pattern,
             context_keywords="[]", window_size=30, mask_text=mask, priority=priority, enabled=True, version=1)
        for code, name, type_code, pattern, mask, priority in defaults
    ]

"""表格感知敏感内容过滤测试。"""

import re

import pytest

from app.services.sensitive_content_service import CompiledRule, SensitiveContentService, SensitiveRuntimeFilter
from app.services.table_sensitive_filter import TABLE_MASK


def table_rule(code: str, type_code: str, pattern: str, mask: str, priority: int) -> CompiledRule:
    return CompiledRule(code, type_code, "table_column", re.compile(pattern), (), 30, mask, priority)


def structural_rule(code: str, type_code: str, match_type: str, pattern: str, mask: str) -> CompiledRule:
    return CompiledRule(code, type_code, match_type, re.compile(pattern), (), 30, mask, 10)


RULES = (
    table_rule("supplier", "supplier_price", r"供应商报价|采购报价|供应商价格|供应商单价|供货价", "[供应商报价已隐藏]", 5),
    table_rule("price", "price", r"报价|价格|单价|总价|供货价", "[报价信息已隐藏]", 10),
    table_rule("cost", "cost", r"成本|采购成本|成本价|采购价", "[成本信息已隐藏]", 20),
    table_rule("margin", "gross_margin", r"毛利率|利润率|毛利", "[利润率信息已隐藏]", 30),
    table_rule("contract", "contract_amount", r"合同金额|合同总价|合同价", "[合同金额已隐藏]", 40),
    table_rule("payment", "payment_terms", r"付款条件|付款方式|预付款|尾款|账期", "[付款条件已隐藏]", 50),
)


def apply(content: str, allowed: set[str] | None = None):
    return SensitiveRuntimeFilter().filter(content, allowed or set(), RULES)


def test_markdown_price_columns_are_redacted() -> None:
    result = apply("| 设备 | 数量 | 单价 | 总价 |\n|---|---:|---:|---:|\n| A | 2 | 35 万元 | 70 万元 |")
    assert "35 万元" not in result.safe_content
    assert "70 万元" not in result.safe_content
    assert result.redaction_count == 2
    assert result.redaction_types == ("price",)


def test_supplier_price_rule_wins_over_generic_price() -> None:
    result = apply("| 设备 | 供应商报价 |\n|---|---:|\n| A | 35 万元 |")
    assert "[供应商报价已隐藏]" in result.safe_content
    assert "[报价信息已隐藏]" not in result.safe_content
    assert result.redaction_types == ("supplier_price",)


def test_horizontal_metric_rows_are_redacted() -> None:
    result = apply("| 指标 | 数值 |\n|---|---:|\n| 报价 | 70 万元 |\n| 成本 | 50 万元 |\n| 毛利率 | 28% |")
    assert "70 万元" not in result.safe_content
    assert "50 万元" not in result.safe_content
    assert "28%" not in result.safe_content
    assert set(result.redaction_types) == {"price", "cost", "gross_margin"}


def test_process_parameter_table_is_not_redacted() -> None:
    content = "| 参数 | 数值 |\n|---|---:|\n| 硫酸浓度 | 20% |\n| 镍回收率 | 98% |\n| 反应温度 | 80℃ |"
    assert apply(content).safe_content == content


def test_payment_terms_table_is_redacted() -> None:
    result = apply("| 合同 | 付款条件 |\n|---|---|\n| A | 预付30%，验收后付尾款 |")
    assert "预付30%" not in result.safe_content
    assert "[付款条件已隐藏]" in result.safe_content


@pytest.mark.parametrize(
    "content",
    [
        "<table><tr><th>设备</th><th>单价</th></tr><tr><td>A</td><td>35 万元</td></tr></table>",
        "设备,数量,单价\nA,2,35 万元",
        "设备\t数量\t单价\nA\t2\t35 万元",
        "设备    数量    单价\nA       2       35万元",
    ],
)
def test_supported_table_formats_are_redacted(content: str) -> None:
    result = apply(content)
    assert "35" not in result.safe_content
    assert result.redacted


def test_malformed_high_risk_table_is_hidden() -> None:
    content = "供应商报价单\n设备,供应商报价,备注\nA,35 万元\nB,40 万元,含税"
    result = apply(content)
    assert TABLE_MASK in result.safe_content
    assert "35 万元" not in result.safe_content


def test_allowed_table_type_remains_visible() -> None:
    content = "| 设备 | 单价 |\n|---|---:|\n| A | 35 万元 |"
    assert apply(content, {"price"}).safe_content == content


def test_explicit_table_row_and_cell_rules_are_supported() -> None:
    rules = (
        structural_rule("row", "cost", "table_row", r"内部成本", "[成本信息已隐藏]"),
        structural_rule("cell", "business_strategy", "table_cell", r"底价不外传", "[商务策略信息已隐藏]"),
    )
    content = "| 指标 | 一期 | 二期 |\n|---|---|---|\n| 内部成本 | 20 万元 | 30 万元 |\n| 备注 | 底价不外传 | 常规说明 |"
    result = SensitiveRuntimeFilter().filter(content, set(), rules)
    assert "20 万元" not in result.safe_content
    assert "30 万元" not in result.safe_content
    assert "底价不外传" not in result.safe_content
    assert set(result.redaction_types) == {"cost", "business_strategy"}


def test_fallback_service_filters_all_sensitive_table_values() -> None:
    content = "| 设备 | 供应商报价 | 成本 | 毛利率 |\n|---|---:|---:|---:|\n| A | 35 万元 | 20 万元 | 42% |"
    result = SensitiveContentService(None).filter_for_user(content, object())
    assert all(value not in result.safe_content for value in ("35 万元", "20 万元", "42%"))
    assert {"supplier_price", "cost", "gross_margin"}.issubset(result.redaction_types)


def test_final_answer_text_fallback_still_applies_after_table_filter() -> None:
    content = "| 设备 | 单价 |\n|---|---:|\n| A | 35 万元 |\n补充报价为 50 万元。"
    result = SensitiveContentService(None).filter_for_user(content, object())
    assert "35 万元" not in result.safe_content
    assert "50 万元" not in result.safe_content

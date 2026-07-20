"""敏感内容运行时过滤测试。"""

import re

from app.services.sensitive_content_service import CompiledRule, SensitiveContentService, SensitiveRuntimeFilter

AMOUNT = r"(?:(?:USD|CNY|RMB|￥|¥|\$)\s*\d+(?:\.\d+)?(?:\s*(?:万|亿|千)?\s*(?:元|人民币|美元|美金))?|\d+(?:\.\d+)?\s*(?:万|亿|千)?\s*(?:元|人民币|美元|美金))(?:\s*/\s*[\u4e00-\u9fa5A-Za-z]+)?"


def rule(code: str, type_code: str, pattern: str, keywords: tuple[str, ...], mask: str, priority: int) -> CompiledRule:
    return CompiledRule(code, type_code, "keyword_window", re.compile(pattern), keywords, 30, mask, priority)


RULES = (
    rule("price", "price", AMOUNT, ("报价", "价格", "销售价", "合同价", "总价"), "[报价信息已隐藏]", 10),
    rule("cost", "cost", AMOUNT, ("成本", "采购成本", "设备成本"), "[成本信息已隐藏]", 20),
    rule("margin", "gross_margin", r"\d+(?:\.\d+)?\s*%", ("毛利率", "利润率", "毛利", "利润空间"), "[利润率信息已隐藏]", 30),
)


def apply(content: str, allowed: set[str] | None = None):
    return SensitiveRuntimeFilter().filter(content, allowed or set(), RULES)


def test_price_is_redacted_without_permission() -> None:
    assert apply("本项目报价为 1350 万元。").safe_content == "本项目报价为 [报价信息已隐藏]。"


def test_price_is_visible_with_permission() -> None:
    text = "本项目报价为 1350 万元。"
    assert apply(text, {"price"}).safe_content == text


def test_cost_and_margin_are_redacted() -> None:
    result = apply("设备采购成本约 820 万元，预计毛利率为 18%。")
    assert result.safe_content == "设备采购成本约 [成本信息已隐藏]，预计毛利率为 [利润率信息已隐藏]。"
    assert set(result.redaction_types) == {"cost", "gross_margin"}


def test_process_parameters_are_not_false_positives() -> None:
    text = "硫酸浓度为 20%，镍回收率达到 98%，反应温度为 80℃。"
    assert apply(text).safe_content == text


def test_more_process_parameters_are_not_false_positives() -> None:
    text = "液固比为 5:1，处理量为 2000 t/a，物料粒径为 5mm。"
    assert SensitiveContentService(None).filter_for_user(text, object()).safe_content == text


def test_multiple_sensitive_types_are_redacted() -> None:
    result = apply("本项目报价为 1350 万元，设备成本为 820 万元，毛利率为 18%。")
    assert result.safe_content == "本项目报价为 [报价信息已隐藏]，设备成本为 [成本信息已隐藏]，毛利率为 [利润率信息已隐藏]。"
    assert result.redaction_count == 3


def test_currency_variants_are_supported() -> None:
    assert apply("商务报价 USD 800000。供货价格为 3.5 万元/吨。").redaction_count == 2


def test_supplier_price_uses_specific_sensitive_type() -> None:
    result = SensitiveContentService(None).filter_for_user("供应商报价为 500 万元。", object())
    assert result.safe_content == "供应商报价为 [供应商报价已隐藏]。"
    assert result.redaction_types == ("supplier_price",)


def test_business_strategy_and_financial_metric_are_redacted() -> None:
    result = SensitiveContentService(None).filter_for_user("本次谈判空间较大，项目 IRR 表现良好。", object())
    assert "[商务策略信息已隐藏]" in result.safe_content
    assert "[财务指标已隐藏]" in result.safe_content


def test_contract_amount_and_payment_terms_are_redacted() -> None:
    service = SensitiveContentService(None)
    result = service.filter_for_user("合同金额为 100 万元，付款条件为预付款 30%，验收后支付尾款。", object())
    assert "[合同金额已隐藏]" in result.safe_content
    assert "[付款条件已隐藏]" in result.safe_content
    assert {"contract_amount", "payment_terms"}.issubset(result.redaction_types)

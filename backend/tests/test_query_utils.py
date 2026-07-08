"""
Retrieval query utility tests.

验证元素符号等短英文 token 不会被普通英文单词子串误召回。
"""

from __future__ import annotations

import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE_DIR))

from app.retrieval.query_utils import (  # noqa: E402
    augment_query_terms,
    count_search_token,
    extract_query_terms,
    is_structured_list_lookup_query,
    score_text_relevance,
)


def test_element_symbol_uses_word_boundary() -> None:
    """Co 应命中独立元素符号，不应命中 corrosion。"""

    assert count_search_token("corrosion allowance", "co") == 0
    assert count_search_token("| 3 | co | wt% | 20 | 40 | 3.211 |", "co") == 1
    assert count_search_token("ni-co-mn compound", "co") == 1
    assert count_search_token("suzhou botree cycling sci & tech co., ltd", "co") == 0
    assert count_search_token("$na_{2}co_{3}$", "co") == 0


def test_table_row_scores_above_corrosion_for_co_min_max_query() -> None:
    """查询 Co 最大/最小时，正确表格行的相关性应高于 corrosion 噪声。"""

    query = "Co的最大值和最小值是多少"
    terms = extract_query_terms(query)
    table_text = "| No. | Element | Percentage | Min | Max | Calculation in design |\n| 3 | Co | wt% | 20 | 40 | 3.211 |"
    corrosion_text = "Corrosion allowance shall be determined according to Botree practice."

    assert "co" in terms
    assert score_text_relevance(table_text, query, terms) > score_text_relevance(corrosion_text, query, terms)


def test_table_value_query_demotes_project_header_without_target_element() -> None:
    """项目页眉和 max/min 泛词不应排在目标元素表格行前面。"""

    query = "2 x 2000 TPA Battery Black Mass Recycling Project项目中 Co的最大值和最小值"
    terms = extract_query_terms(query)
    table_text = (
        "2 x 2000 TPA Battery Black Mass Recycling Project\n"
        "| No. | Element | Percentage | Min | Max | Calculation in design |\n"
        "| 3 | Co | wt% | 20 | 40 | 3.211 |"
    )
    header_text = (
        "2 x 2000 TPA Battery Black Mass Recycling Project\n"
        "SUZHOU BOTREE CYCLING SCI & TECH CO., LTD\n"
        "Maximum suction pressure and minimum design temperature."
    )

    assert score_text_relevance(table_text, query, terms) > score_text_relevance(header_text, query, terms)


def test_structured_list_lookup_adds_product_alias_terms() -> None:
    query = "该项目的最终产品有哪些"
    terms = set(augment_query_terms(query))

    assert is_structured_list_lookup_query(query) is True
    assert {"Product List", "Product Name", "Products"}.issubset(terms)
    assert {"List", "Table", "Name"}.isdisjoint(terms)

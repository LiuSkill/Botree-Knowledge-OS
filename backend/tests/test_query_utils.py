"""
Retrieval query utility tests.
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
    assert count_search_token("corrosion allowance", "co") == 0
    assert count_search_token("| 3 | co | wt% | 20 | 40 | 3.211 |", "co") == 1
    assert count_search_token("ni-co-mn compound", "co") == 1
    assert count_search_token("suzhou botree cycling sci & tech co., ltd", "co") == 0
    assert count_search_token("$na_{2}co_{3}$", "co") == 0


def test_table_row_scores_above_corrosion_for_co_min_max_query() -> None:
    query = "Co的最大值和最小值是多少"
    terms = extract_query_terms(query)
    table_text = "| No. | Element | Percentage | Min | Max | Calculation in design |\n| 3 | Co | wt% | 20 | 40 | 3.211 |"
    corrosion_text = "Corrosion allowance shall be determined according to Botree practice."

    assert "co" in terms
    assert score_text_relevance(table_text, query, terms) > score_text_relevance(corrosion_text, query, terms)


def test_table_value_query_demotes_project_header_without_target_element() -> None:
    query = "2 x 2000 TPA Battery Black Mass Recycling Project项目中Co的最大值和最小值是多少"
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


def test_structured_list_query_demotes_generic_table_without_target_anchor() -> None:
    query = "该项目的最终产品有哪些"
    terms = extract_query_terms(query)
    product_table = (
        "BCE2413 Product List_Rev.1B.pdf\n"
        "| No. | Product Name | Product Remarks |\n"
        "| 1 | Li2CO3 | / |"
    )
    generic_table = (
        "2 x 2000 TPA Battery Black Mass Recycling Project\n"
        "PERFORMANCE TEST OF THE PUMP\n"
        "| No. | Test Item | Result | Unit |\n"
        "| 1 | Flow rate | 12 | m3/h |"
    )

    assert score_text_relevance(product_table, query, terms) > score_text_relevance(generic_table, query, terms)

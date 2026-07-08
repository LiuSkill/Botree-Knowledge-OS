"""Query profile service tests."""

from __future__ import annotations

import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE_DIR))

from app.services.query_profile_service import QueryProfileService  # noqa: E402


def test_pure_general_profile_uses_none_scope() -> None:
    profile = QueryProfileService().build_profile("1+1=几", intent="pure_general_qa")

    assert profile["query_type"] == "pure_general_qa"
    assert profile["answer_shape"] == "direct_answer"
    assert profile["knowledge_scope"] == "none"
    assert profile["is_industry_domain"] is False
    assert profile["industry_domains"] == []


def test_industry_profile_marks_domain_and_industry_scope() -> None:
    profile = QueryProfileService().build_profile("P&ID 图怎么看", intent="industry_knowledge_qa")

    assert profile["query_type"] == "industry_knowledge_qa"
    assert profile["knowledge_scope"] == "industry"
    assert profile["is_industry_domain"] is True
    assert "pid_pfd" in profile["industry_domains"]


def test_project_profile_priority_over_industry_terms() -> None:
    profile = QueryProfileService().build_profile("BMI 项目的酸浸流程是什么", intent="project_qa")

    assert profile["query_type"] == "process_flow"
    assert profile["knowledge_scope"] == "project"
    assert profile["need_visual_asset"] is True
    assert profile["is_industry_domain"] is True
    assert "hydrometallurgy" in profile["industry_domains"]


def test_project_name_does_not_force_exact_lookup() -> None:
    profile = QueryProfileService().build_profile(
        "Introduce 2 x 2000 TPA Battery Black Mass Recycling Project",
        intent="project_overview",
    )

    assert profile["query_type"] == "project_overview"
    assert profile["answer_shape"] == "project_summary"
    assert profile["has_project_name"] is True
    assert profile["need_exact_term"] is False
    assert profile["need_page_location"] is False


def test_process_flow_query_without_explicit_drawing_keyword_still_requests_visual_assets() -> None:
    profile = QueryProfileService().build_profile("Na2SO4蒸发流程", intent="project_qa")

    assert profile["query_type"] == "process_flow"
    assert profile["answer_shape"] == "process_steps"
    assert profile["need_visual_asset"] is True

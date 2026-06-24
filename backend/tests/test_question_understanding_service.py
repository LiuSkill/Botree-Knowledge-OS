"""QuestionUnderstanding service tests."""

from __future__ import annotations

import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE_DIR))

from app.services.question_understanding_service import (  # noqa: E402
    AnswerPolicy,
    AnswerShape,
    KnowledgeScope,
    QueryNormalizerService,
    QuestionUnderstandingService,
    TaskType,
)


def test_black_mass_feeding_rewrites_include_project_search_terms() -> None:
    rewrites = QueryNormalizerService().build_query_rewrites("本项目的黑粉进料流程介绍")

    assert "本项目的黑粉进料流程介绍" in rewrites
    assert "黑粉 进料 流程" in rewrites
    assert "Black Mass Feeding" in rewrites
    assert "Raw Material Feeding" in rewrites
    assert "Raw Material & Chemical Feeding" in rewrites


def test_project_black_mass_feeding_is_understood_as_process_flow() -> None:
    understanding = QuestionUnderstandingService().understand(
        "本项目的黑粉进料流程介绍",
        chat_type="project_chat",
        project_id=1,
        user_id=7,
        intent="project_overview",
        query_profile={"query_type": "project_overview", "entities": ["BMI"]},
    ).to_dict()

    assert understanding["task_type"] == TaskType.PROCESS_FLOW.value
    assert understanding["answer_shape"] == AnswerShape.PROCESS_STEPS.value
    assert understanding["answer_policy"] == AnswerPolicy.STRICT_KB.value
    assert understanding["knowledge_scope"] == KnowledgeScope.PROJECT.value
    assert understanding["retrieval_needs"]["graph_retrieval"] is True
    assert "Black Mass Feeding" in understanding["query_rewrites"]
    assert "Raw Material Feeding" in understanding["query_rewrites"]


def test_project_overview_question_remains_project_overview() -> None:
    understanding = QuestionUnderstandingService().understand(
        "本项目概况介绍",
        chat_type="project_chat",
        project_id=1,
        user_id=7,
        intent="project_overview",
        query_profile={"query_type": "project_overview"},
    ).to_dict()

    assert understanding["task_type"] == TaskType.PROJECT_OVERVIEW.value
    assert understanding["answer_shape"] == AnswerShape.PROJECT_SUMMARY.value


def test_visual_material_flow_is_understood_as_process_flow() -> None:
    understanding = QuestionUnderstandingService().understand(
        "这张图里的物料流向是什么",
        chat_type="project_chat",
        project_id=1,
        user_id=7,
        intent="project_qa",
        query_profile={"query_type": "project_qa"},
    ).to_dict()

    assert understanding["task_type"] == TaskType.PROCESS_FLOW.value
    assert understanding["answer_shape"] == AnswerShape.PROCESS_STEPS.value
    assert understanding["object_type"] == "material_flow"
    assert understanding["retrieval_needs"]["visual_evidence"] is True


def test_drawing_page_location_is_understood_as_document_location() -> None:
    understanding = QuestionUnderstandingService().understand(
        "黑粉进料流程在哪张图纸第几页",
        chat_type="project_chat",
        project_id=1,
        user_id=7,
        intent="project_qa",
        query_profile={"query_type": "page_location"},
    ).to_dict()

    assert understanding["task_type"] == TaskType.DOCUMENT_LOCATION.value
    assert understanding["answer_shape"] == AnswerShape.SOURCE_LOCATION.value
    assert understanding["retrieval_needs"]["exact_text_search"] is True
    assert understanding["retrieval_needs"]["page_level_retrieval"] is True


def test_industry_definition_keeps_industry_scope() -> None:
    understanding = QuestionUnderstandingService().understand(
        "酸浸原理是什么",
        chat_type="base_chat",
        project_id=None,
        user_id=7,
        intent="industry_knowledge_qa",
        query_profile={"query_type": "industry_knowledge_qa"},
    ).to_dict()

    assert understanding["task_type"] == TaskType.DEFINITION.value
    assert understanding["knowledge_scope"] == KnowledgeScope.INDUSTRY.value
    assert understanding["answer_policy"] == AnswerPolicy.KB_FIRST.value

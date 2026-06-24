"""PolicyResolver service tests."""

from __future__ import annotations

import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE_DIR))

from app.services.policy_resolver_service import PolicyResolver  # noqa: E402
from app.services.question_understanding_service import AnswerPolicy, AnswerShape, KnowledgeScope, TaskType  # noqa: E402


def test_process_flow_understanding_overrides_project_overview_intent() -> None:
    resolution = PolicyResolver().resolve(
        chat_type="project_chat",
        project_id=1,
        user_id=7,
        intent="project_overview",
        query_profile={"query_type": "project_overview", "answer_shape": "project_summary"},
        question_understanding={
            "task_type": TaskType.PROCESS_FLOW.value,
            "answer_shape": AnswerShape.PROCESS_STEPS.value,
            "knowledge_scope": KnowledgeScope.PROJECT.value,
        },
    ).to_dict()

    assert resolution["original_intent"] == "project_overview"
    assert resolution["resolved_task_type"] == TaskType.PROCESS_FLOW.value
    assert resolution["resolved_answer_shape"] == AnswerShape.PROCESS_STEPS.value
    assert resolution["answer_shape"] == AnswerShape.PROCESS_STEPS.value
    assert resolution["answer_policy"] == AnswerPolicy.STRICT_KB.value
    assert resolution["knowledge_scope"] == KnowledgeScope.PROJECT.value
    assert resolution["conflict_detected"] is True
    assert "question_understanding_process_flow_priority" in resolution["resolution_rule"]


def test_project_overview_signals_stay_project_overview() -> None:
    resolution = PolicyResolver().resolve(
        chat_type="project_chat",
        project_id=1,
        user_id=7,
        intent="project_overview",
        query_profile={"query_type": "project_overview", "answer_shape": "project_summary"},
        question_understanding={
            "task_type": TaskType.PROJECT_OVERVIEW.value,
            "answer_shape": AnswerShape.PROJECT_SUMMARY.value,
            "knowledge_scope": KnowledgeScope.PROJECT.value,
        },
    ).to_dict()

    assert resolution["resolved_task_type"] == TaskType.PROJECT_OVERVIEW.value
    assert resolution["resolved_answer_shape"] == AnswerShape.PROJECT_SUMMARY.value
    assert resolution["answer_policy"] == AnswerPolicy.STRICT_KB.value
    assert resolution["conflict_detected"] is False


def test_query_profile_process_flow_has_priority_when_understanding_is_not_flow() -> None:
    resolution = PolicyResolver().resolve(
        chat_type="base_chat",
        project_id=None,
        user_id=7,
        intent="knowledge_qa",
        query_profile={"query_type": "process_flow", "answer_shape": "process_steps"},
        question_understanding={
            "task_type": TaskType.DEFINITION.value,
            "answer_shape": AnswerShape.DIRECT_ANSWER.value,
            "knowledge_scope": KnowledgeScope.INDUSTRY.value,
        },
    ).to_dict()

    assert resolution["resolved_task_type"] == TaskType.PROCESS_FLOW.value
    assert resolution["resolved_answer_shape"] == AnswerShape.PROCESS_STEPS.value
    assert resolution["answer_policy"] == AnswerPolicy.KB_FIRST.value
    assert resolution["knowledge_scope"] == KnowledgeScope.INDUSTRY.value
    assert resolution["conflict_detected"] is True
    assert resolution["resolution_rule"] == "query_profile_process_flow_priority"

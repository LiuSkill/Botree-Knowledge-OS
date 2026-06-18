"""Answer prompt profile tests."""

from __future__ import annotations

import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE_DIR))

from app.retrieval.schemas import Evidence  # noqa: E402
from app.services.llm_service import INDUSTRY_GENERAL_KNOWLEDGE_NOTICE, LLMService  # noqa: E402


def make_evidence(source_type: str = "project", project_id: int | None = 1, content: str = "设计温度为 80 °C。") -> Evidence:
    return Evidence(
        score=0.95,
        source_type=source_type,
        knowledge_base_id=1,
        project_id=project_id,
        document_id=11,
        chunk_id=101,
        drawing_no="D-001",
        file_name="design.pdf",
        page_number=3,
        content=content,
        retriever="ripgrep",
    )


def user_prompt_for(profile: dict) -> str:
    service = object.__new__(LLMService)
    messages = service._build_text_messages("设计温度是多少？", [make_evidence()], profile)  # noqa: SLF001
    return messages[1]["content"]


def test_answer_prompt_switches_to_direct_value_template() -> None:
    prompt = user_prompt_for({"query_type": "exact_lookup", "answer_shape": "direct_value"})

    assert "直接回答数值、单位和对象" in prompt
    assert "资料中无法确认" in prompt


def test_answer_prompt_switches_to_process_flow_template() -> None:
    prompt = user_prompt_for({"query_type": "process_flow", "answer_shape": "process_steps"})

    assert "流程步骤：按物料流向逐步说明" in prompt
    assert "关键设备/节点" in prompt


def test_answer_prompt_switches_to_source_location_template() -> None:
    prompt = user_prompt_for({"query_type": "page_location", "answer_shape": "source_location"})

    assert "优先回答文件名、图号、页码、chunk/source 编号" in prompt


def test_industry_knowledge_without_evidence_uses_general_model_with_notice() -> None:
    service = object.__new__(LLMService)
    captured: dict[str, object] = {}

    def fake_chat(
        messages: list[dict[str, str]],
        model_type: str = "llm",
        timeout_seconds: int | None = None,  # noqa: ARG001
        max_tokens: int | None = None,
        disable_thinking: bool = False,
    ) -> str:
        captured["messages"] = messages
        captured["model_type"] = model_type
        captured["max_tokens"] = max_tokens
        captured["disable_thinking"] = disable_thinking
        return "酸浸通常是利用酸与金属氧化物或盐类反应，使目标金属进入溶液。"

    service.chat = fake_chat  # type: ignore[method-assign]

    answer = service.answer_with_evidence(
        "酸浸原理是什么",
        [],
        model_type="answer_llm",
        query_profile={"knowledge_scope": "industry", "query_type": "industry_knowledge_qa"},
    )

    assert "酸浸通常是利用酸" in answer
    assert answer.endswith(INDUSTRY_GENERAL_KNOWLEDGE_NOTICE)
    assert captured["model_type"] == "answer_llm"
    assert captured["max_tokens"] == 1000
    assert captured["disable_thinking"] is True
    assert "必须给出实质性回答" in captured["messages"][0]["content"]  # type: ignore[index]
    assert "不得编造来源编号" in captured["messages"][0]["content"]  # type: ignore[index]


def test_industry_comparison_without_evidence_also_uses_general_model() -> None:
    service = object.__new__(LLMService)

    def fake_chat(
        messages: list[dict[str, str]],  # noqa: ARG001
        model_type: str = "llm",  # noqa: ARG001
        timeout_seconds: int | None = None,  # noqa: ARG001
        max_tokens: int | None = None,  # noqa: ARG001
        disable_thinking: bool = False,  # noqa: ARG001
    ) -> str:
        return "压滤机通常通过滤布和压力实现固液分离，过滤器更偏向去除流体中的颗粒杂质。"

    service.chat = fake_chat  # type: ignore[method-assign]

    answer = service.answer_with_evidence(
        "压滤机和过滤器有什么区别",
        [],
        model_type="answer_llm",
        query_profile={"knowledge_scope": "industry", "query_type": "comparison"},
    )

    assert "压滤机通常" in answer
    assert answer.endswith(INDUSTRY_GENERAL_KNOWLEDGE_NOTICE)


def test_industry_stream_without_chunks_falls_back_to_sync_answer() -> None:
    service = object.__new__(LLMService)
    captured: dict[str, int] = {"stream_calls": 0, "chat_calls": 0}

    def fake_stream_chat(
        messages: list[dict[str, str]],  # noqa: ARG001
        model_type: str = "llm",  # noqa: ARG001
        timeout_seconds: int | None = None,  # noqa: ARG001
        max_tokens: int | None = None,  # noqa: ARG001
        disable_thinking: bool = False,  # noqa: ARG001
    ):
        captured["stream_calls"] += 1
        if False:
            yield ""

    def fake_chat(
        messages: list[dict[str, str]],  # noqa: ARG001
        model_type: str = "llm",  # noqa: ARG001
        timeout_seconds: int | None = None,  # noqa: ARG001
        max_tokens: int | None = None,  # noqa: ARG001
        disable_thinking: bool = False,  # noqa: ARG001
    ) -> str:
        captured["chat_calls"] += 1
        return "压滤机通过压力差使浆料中的固体截留在滤布上，过滤器通常用于去除流体中的颗粒杂质。"

    service.stream_chat = fake_stream_chat  # type: ignore[method-assign]
    service.chat = fake_chat  # type: ignore[method-assign]

    chunks = list(
        service.stream_answer_with_evidence(
            "压滤机和过滤器有什么区别",
            [],
            model_type="answer_llm",
            query_profile={"knowledge_scope": "industry", "query_type": "comparison"},
        )
    )

    answer = "".join(chunks)
    assert captured == {"stream_calls": 1, "chat_calls": 1}
    assert "压滤机通过压力差" in answer
    assert answer.endswith(INDUSTRY_GENERAL_KNOWLEDGE_NOTICE)


def test_industry_sync_empty_answer_retries_with_direct_prompt() -> None:
    service = object.__new__(LLMService)
    captured: dict[str, object] = {"calls": 0, "prompts": []}

    def fake_chat(
        messages: list[dict[str, str]],
        model_type: str = "llm",  # noqa: ARG001
        timeout_seconds: int | None = None,  # noqa: ARG001
        max_tokens: int | None = None,  # noqa: ARG001
        disable_thinking: bool = False,
    ) -> str:
        captured["calls"] = int(captured["calls"]) + 1
        captured["disable_thinking"] = disable_thinking
        cast_prompts = captured["prompts"]
        assert isinstance(cast_prompts, list)
        cast_prompts.append(messages[0]["content"])
        if captured["calls"] == 1:
            return ""
        return "压滤机适合处理含固量较高的浆料，过滤器更常用于液体或气体中颗粒杂质的去除。"

    service.chat = fake_chat  # type: ignore[method-assign]

    answer = service.answer_with_evidence(
        "压滤机和过滤器有什么区别",
        [],
        model_type="answer_llm",
        query_profile={"knowledge_scope": "industry", "query_type": "comparison"},
    )

    prompts = captured["prompts"]
    assert isinstance(prompts, list)
    assert captured["calls"] == 2
    assert captured["disable_thinking"] is True
    assert "必须给出实质性回答" in prompts[0]
    assert "不要提知识库无资料" in prompts[1]
    assert "压滤机适合处理" in answer
    assert "无法给出基于资料" not in answer
    assert answer.endswith(INDUSTRY_GENERAL_KNOWLEDGE_NOTICE)


def test_project_with_industry_prompt_keeps_project_evidence_primary() -> None:
    service = object.__new__(LLMService)
    evidences = [
        make_evidence("project", 1, "项目资料明确：酸浸温度为 80 °C。"),
        make_evidence("authorized_internal", None, "行业知识：酸浸通常利用酸与金属氧化物反应。"),
    ]

    messages = service._build_text_messages(  # noqa: SLF001
        "BMI 项目的酸浸流程是什么",
        evidences,
        {"knowledge_scope": "project_with_industry", "query_type": "project_qa"},
    )
    prompt = messages[1]["content"]

    assert "必须优先使用 source_type=project 的项目资料证据" in prompt
    assert "行业知识补充/原理说明" in prompt
    assert "不得替代项目资料生成项目参数、设备、流程或专有结论" in prompt
    assert "source_type=project" in prompt
    assert "source_type=authorized_internal" in prompt

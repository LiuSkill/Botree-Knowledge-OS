"""
Model Routing Tests

负责：
1. 验证项目问答任务模型默认配置会写入数据库
2. 验证不同任务按 model_type 选择数据库/环境兜底模型
3. 避免单元测试访问真实外部 LLM
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import requests
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

BASE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE_DIR))

from app.core import database as database_module  # noqa: E402
from app.core.exceptions import AppException  # noqa: E402
from app.agent.answer_generator import AnswerGenerator  # noqa: E402
from app.models.base import Base  # noqa: E402
from app.models.model_config import ModelConfig  # noqa: E402
from app.retrieval.schemas import Evidence, EvidenceAsset  # noqa: E402
from app.services.llm_service import LLMService, RuntimeModelConfig  # noqa: E402
from app.services.qwen_orchestration_service import QwenOrchestrationService  # noqa: E402
from app.services.retrieval_planner_service import RetrievalPlannerService  # noqa: E402


def make_session() -> Session:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True)()


def fake_settings() -> SimpleNamespace:
    return SimpleNamespace(
        llm_provider="qwen_api",
        llm_base_url="https://dashscope.example/v1",
        llm_api_key="secret",
        llm_model="qwen3.7-max",
        llm_timeout_seconds=60,
        openai_compatible_base_url=None,
        openai_api_key=None,
        intent_llm_model="qwen3.5-flash",
        planner_llm_model="qwen3.5-flash",
        evidence_judge_fast_model="qwen3.5-flash",
        evidence_judge_model="qwen3.5-plus",
        evidence_judge_timeout_seconds=90,
        answer_llm_model="qwen3.5-plus",
        analysis_llm_model="qwen3.7-max",
        vision_llm_provider="qwen_api",
        vision_llm_base_url="https://dashscope.example/v1",
        vision_llm_api_key="vision-secret",
        vision_llm_model="qwen3.5-plus",
        vision_llm_timeout_seconds=90,
        embedding_provider="local",
        embedding_model=None,
    )


def make_evidence(content: str = "项目资料显示该流程包含原料输送、计量、控制和下游连接，信息可用于回答。") -> Evidence:
    return Evidence(
        score=0.92,
        source_type="project",
        knowledge_base_id=1,
        project_id=1,
        document_id=11,
        chunk_id=101,
        drawing_no="10-PS-0101-3002-003",
        file_name="pid.pdf",
        page_number=1,
        content=content,
        retriever="milvus",
        metadata={"security_level": "public"},
    )


def test_seed_task_model_configs_inserts_missing_defaults_without_overwriting(monkeypatch) -> None:
    db = make_session()
    try:
        db.add(
            ModelConfig(
                provider="custom",
                model_name="custom-intent",
                api_base="https://custom.example/v1",
                api_key=None,
                model_type="intent",
                is_default=True,
                enabled=True,
            )
        )
        db.commit()
        monkeypatch.setattr(database_module, "get_settings", fake_settings)

        database_module.seed_model_config(db)
        db.commit()

        configs = {
            item.model_type: item
            for item in db.scalars(select(ModelConfig).where(ModelConfig.is_default.is_(True))).all()
        }
        assert configs["intent"].model_name == "custom-intent"
        assert configs["planner"].model_name == "qwen3.5-flash"
        assert configs["evidence_judge_fast"].model_name == "qwen3.5-flash"
        assert configs["evidence_judge"].model_name == "qwen3.5-plus"
        assert configs["answer_llm"].model_name == "qwen3.5-plus"
        assert configs["vision_llm"].model_name == "qwen3.5-plus"
        assert configs["analysis_llm"].model_name == "qwen3.7-max"
        assert configs["planner"].api_key is None
    finally:
        db.close()


def test_llm_service_uses_task_model_env_fallback() -> None:
    service = object.__new__(LLMService)
    service.settings = fake_settings()
    service.model_repository = SimpleNamespace(get_default=lambda _: None)

    runtime_config = service._runtime_config("answer_llm")  # noqa: SLF001

    assert runtime_config.model_type == "answer_llm"
    assert runtime_config.model_name == "qwen3.5-plus"
    assert runtime_config.source == "env_fallback"


def test_llm_service_caps_evidence_judge_timeout_and_sanitizes_timeout(monkeypatch) -> None:
    db = make_session()
    captured: dict[str, Any] = {}

    def fake_runtime_config(model_type: str, config=None) -> RuntimeModelConfig:  # noqa: ANN001
        return RuntimeModelConfig(
            provider="qwen_api",
            model_name="qwen3.5-plus",
            api_base="https://dashscope.example/v1",
            api_key="secret",
            model_type=model_type,
        )

    def fake_post(url: str, headers: dict[str, str], json: dict[str, Any], timeout: int):  # noqa: A002, ARG001
        captured["json"] = json
        captured["timeout"] = timeout
        raise requests.ReadTimeout("HTTPSConnectionPool(host='dashscope.aliyuncs.com')")

    try:
        service = LLMService(db)
        monkeypatch.setattr(service, "_runtime_config", fake_runtime_config)
        monkeypatch.setattr("app.services.llm_service.requests.post", fake_post)

        try:
            service.chat(
                [{"role": "user", "content": "判断证据是否足够"}],
                model_type="evidence_judge",
                timeout_seconds=90,
                max_tokens=512,
            )
        except AppException as exc:
            assert exc.status_code == 504
            assert exc.message == "LLM接口响应超时，请稍后重试"
            assert "dashscope" not in exc.message
        else:
            raise AssertionError("evidence judge timeout must be converted to AppException")

        assert captured["timeout"] == 15
        assert captured["json"]["enable_thinking"] is False
        assert captured["json"]["response_format"] == {"type": "json_object"}
        assert captured["json"]["max_completion_tokens"] == 512
        assert "max_tokens" not in captured["json"]
        assert service.last_timeout_seconds == 15
    finally:
        db.close()


def test_llm_connection_test_payload_does_not_force_json_mode() -> None:
    service = object.__new__(LLMService)
    runtime_config = RuntimeModelConfig(
        provider="qwen_api",
        model_name="qwen3.5-plus",
        api_base="https://dashscope.example/v1",
        api_key="secret",
        model_type="evidence_judge",
    )

    payload = service._build_chat_payload(  # noqa: SLF001
        runtime_config,
        [{"role": "user", "content": "请回复：连接正常"}],
        apply_task_options=False,
    )

    assert "enable_thinking" not in payload
    assert "response_format" not in payload


def test_disable_thinking_payload_option_for_answer_model() -> None:
    service = object.__new__(LLMService)
    runtime_config = RuntimeModelConfig(
        provider="qwen_api",
        model_name="qwen3.5-plus",
        api_base="https://dashscope.example/v1",
        api_key="secret",
        model_type="answer_llm",
    )

    payload = service._build_chat_payload(  # noqa: SLF001
        runtime_config,
        [{"role": "user", "content": "请直接回答"}],
        disable_thinking=True,
    )

    assert payload["enable_thinking"] is False
    assert "response_format" not in payload


def test_intent_fallback_uses_intent_model_type() -> None:
    captured: dict[str, Any] = {}

    class FakeLLMService:
        def __init__(self, db: object) -> None:  # noqa: D107
            self.db = db

        def chat(self, messages: list[dict[str, str]], model_type: str = "llm") -> str:  # noqa: ARG002
            captured["model_type"] = model_type
            return '{"intent":"project_qa"}'

        def model_route(self, task: str, reason: str) -> dict[str, Any]:
            return {"task": task, "model_type": captured["model_type"], "source": "database", "reason": reason}

    question = "请基于当前资料详细说明系统整体情况、主要内容、关键设备和使用注意事项。" * 4
    with patch("app.services.qwen_orchestration_service.LLMService", FakeLLMService):
        service = QwenOrchestrationService(db=None)  # type: ignore[arg-type]
        intent = service.detect_intent(question, "base_chat", "auto")

    assert intent == "project_qa"
    assert captured["model_type"] == "intent"
    assert service.model_routes["intent"]["model_type"] == "intent"


def test_planner_qwen_path_uses_planner_model_type() -> None:
    captured: dict[str, Any] = {}

    class FakeLLMService:
        def __init__(self, db: object) -> None:  # noqa: D107
            self.db = db

        def chat(self, messages: list[dict[str, str]], model_type: str = "llm") -> str:  # noqa: ARG002
            captured["model_type"] = model_type
            return '{"selected_retrievers":["milvus","keyword"],"reason":"model plan","confidence":0.91}'

        def model_route(self, task: str, reason: str) -> dict[str, Any]:
            return {"task": task, "model_type": captured["model_type"], "source": "database", "reason": reason}

    with patch("app.services.retrieval_planner_service.LLMService", FakeLLMService):
        plan = RetrievalPlannerService(db=object()).plan(
            query="请综合分析上下游关系和影响",
            sub_queries=["请综合分析上下游关系和影响"],
            intent="graph_reasoning",
            chat_type="project_chat",
            mode="hybrid",
            project_id=1,
            available_retrievers=["milvus", "keyword", "graphrag"],
        )

    assert plan.qwen_used is True
    assert captured["model_type"] == "planner"
    assert plan.metadata["model_route"]["model_type"] == "planner"


def test_answer_generator_selects_text_vision_and_analysis_models() -> None:
    generator = object.__new__(AnswerGenerator)
    text_evidence = make_evidence()
    complex_evidences = [make_evidence(f"综合分析资料 {index}：包含上下游关系、影响原因和跨系统接口。") for index in range(5)]
    visual_evidence = make_evidence()
    visual_evidence.assets.append(
        EvidenceAsset(
            asset_id=1,
            asset_type="page_preview",
            url="/api/documents/assets/1",
            mime_type="image/png",
            file_name="pid.png",
            file_size=128,
            page_number=1,
        )
    )

    assert generator._select_answer_model("普通文本问题", [text_evidence])[0] == "answer_llm"  # noqa: SLF001
    assert generator._select_answer_model("请说明图纸流程", [visual_evidence])[0] == "vision_llm"  # noqa: SLF001
    assert generator._select_answer_model("请综合分析上下游关系和影响原因", complex_evidences)[0] == "analysis_llm"  # noqa: SLF001


def test_answer_generator_refusal_reason_uses_chinese_label() -> None:
    """项目问答拒答原因面向用户时不应暴露内部英文 code。"""

    generator = object.__new__(AnswerGenerator)
    answer = generator._refusal_answer(  # noqa: SLF001
        "哈哈，很好",
        {"risk": "irrelevant"},
        {"query_validity": "valid"},
    )

    assert "拒答原因：问题超出当前知识库或项目范围" in answer
    assert "out_of_scope" not in answer


def test_answer_generator_marks_industry_no_evidence_as_model_fallback() -> None:
    class FakeLLMService:
        def answer_with_evidence(
            self,
            question: str,  # noqa: ARG002
            evidences: list[Evidence],  # noqa: ARG002
            model_type: str = "llm",  # noqa: ARG002
            query_profile: dict[str, Any] | None = None,  # noqa: ARG002
        ) -> str:
            return "模型通用知识回答。"

        def model_route(self, task: str, reason: str) -> dict[str, Any]:
            return {"task": task, "source": "database", "model_type": "answer_llm", "reason": reason}

    generator = object.__new__(AnswerGenerator)
    generator.llm_service = FakeLLMService()

    answer = generator.generate(
        "酸浸原理是什么",
        [],
        query_profile={"knowledge_scope": "industry", "query_type": "industry_knowledge_qa"},
    )

    assert answer == "模型通用知识回答。"
    assert generator.last_model_route == {
        "task": "answer",
        "source": "database",
        "model_type": "answer_llm",
        "reason": "行业知识库未召回证据，使用模型通用知识兜底回答",
    }


def test_visual_evidence_judge_skips_llm_for_simple_drawing_flow() -> None:
    service = QwenOrchestrationService(db=None)  # type: ignore[arg-type]
    evidences = [make_evidence() for _ in range(5)]
    for index, evidence in enumerate(evidences, start=1):
        evidence.assets.append(
            EvidenceAsset(
                asset_id=index,
                asset_type="page_preview",
                url=f"/api/documents/assets/{index}",
                mime_type="image/png",
                file_name=f"pid-{index}.png",
                file_size=128,
                page_number=1,
            )
        )

    result = service.judge_evidence(
        "Raw Material & Chemical Feeding全流程",
        evidences,
        {
            "retriever_hits": {"milvus": 5},
            "query_features": {
                "has_table_value_lookup": False,
                "has_table_hint": False,
                "has_comparison": False,
                "has_graph_relation": False,
            },
        },
    )

    assert result["enough"] is True
    assert service.model_routes["evidence_judge"]["source"] == "rules"


def test_evidence_judge_parse_new_json_fields_and_filters_retrievers() -> None:
    """证据判断新版 JSON 字段需要解析成功，并过滤未知 retriever。"""

    service = QwenOrchestrationService(db=None)  # type: ignore[arg-type]
    result = service._parse_evidence_payload(  # noqa: SLF001
        """
        {
          "enough": false,
          "confidence": 0.76,
          "answerable_parts": ["已有起点"],
          "missing_aspects": ["缺少终点"],
          "best_evidence_indexes": [1, "3", "bad", 0],
          "suggested_retrievers": ["page_index", "unknown", "ripgrep"],
          "suggested_queries": ["PFD 起点终点"],
          "reason": "流程证据不完整"
        }
        """
    )

    assert result["enough"] is False
    assert result["confidence"] == 0.76
    assert result["answerable_parts"] == ["已有起点"]
    assert result["missing_aspects"] == ["缺少终点"]
    assert result["best_evidence_indexes"] == [1, 3]
    assert result["suggested_retrievers"] == ["page_index", "ripgrep"]
    assert result["suggested_queries"] == ["PFD 起点终点"]


def test_evidence_judge_parse_old_json_still_compatible() -> None:
    """老 JSON 只包含 enough/reason 时仍可运行。"""

    service = QwenOrchestrationService(db=None)  # type: ignore[arg-type]
    result = service._parse_evidence_payload('{"enough": true, "reason": "足够"}')  # noqa: SLF001

    assert result["enough"] is True
    assert result["reason"] == "足够"
    assert result["suggested_retrievers"] == []
    assert result["answerable_parts"] == []

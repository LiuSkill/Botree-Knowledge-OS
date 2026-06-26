"""
Visual Evidence Tests

负责：
1. 验证命中页图片资产选择策略
2. 验证多模态 LLM payload 构造
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

BASE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE_DIR))

from app.models import Base, DocumentAsset, DocumentPage, PageIndex  # noqa: E402
from app.retrieval.schemas import Evidence, EvidenceAsset  # noqa: E402
from app.services.document_asset_service import ASSET_TYPE_BLOCK_IMAGE, ASSET_TYPE_PAGE_PREVIEW  # noqa: E402
from app.services.llm_service import LLMService, RuntimeModelConfig  # noqa: E402
from app.services.visual_evidence_service import VisualEvidenceService  # noqa: E402


def make_session() -> Session:
    """创建独立内存数据库会话。"""

    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    return session_factory()


def make_evidence(page_index_id: int | None = None) -> Evidence:
    """创建可挂载视觉资产的检索证据。"""

    metadata: dict[str, Any] = {"security_level": "public"}
    if page_index_id is not None:
        metadata["page_index_id"] = page_index_id
    return Evidence(
        score=1.0,
        source_type="project",
        knowledge_base_id=1,
        project_id=1,
        document_id=11,
        chunk_id=101,
        drawing_no="10-PS-0101-3002-001",
        file_name="pid.pdf",
        page_number=1,
        content="PID page text",
        retriever="page_index",
        metadata=metadata,
    )


def test_visual_evidence_prefers_page_preview_then_largest_block() -> None:
    """有页面预览时，先挂 page_preview，再挂同页最大 block_image。"""

    db = make_session()
    try:
        page = DocumentPage(
            knowledge_base_id=1,
            project_id=1,
            document_id=11,
            version_no=1,
            page_no=1,
            page_text="page",
            correction_status="raw",
        )
        db.add(page)
        db.flush()
        page_index = PageIndex(
            knowledge_base_id=1,
            project_id=1,
            document_id=11,
            page_id=page.id,
            chunk_id=101,
            version_no=1,
            page_no=1,
            index_text="10-PS-0101-3002-001",
            status="published",
        )
        db.add(page_index)
        db.flush()

        preview = DocumentAsset(
            document_id=11,
            version_no=1,
            page_id=page.id,
            asset_type=ASSET_TYPE_PAGE_PREVIEW,
            file_name="page.jpg",
            mime_type="image/jpeg",
            storage_backend="local",
            storage_path="storage/derived/11/v1/page.jpg",
            file_size=100,
            status="ready",
        )
        small_block = DocumentAsset(
            document_id=11,
            version_no=1,
            page_id=page.id,
            block_id=1,
            asset_type=ASSET_TYPE_BLOCK_IMAGE,
            file_name="small.jpg",
            mime_type="image/jpeg",
            storage_backend="local",
            storage_path="storage/derived/11/v1/small.jpg",
            file_size=200,
            status="ready",
        )
        large_block = DocumentAsset(
            document_id=11,
            version_no=1,
            page_id=page.id,
            block_id=2,
            asset_type=ASSET_TYPE_BLOCK_IMAGE,
            file_name="large.jpg",
            mime_type="image/jpeg",
            storage_backend="local",
            storage_path="storage/derived/11/v1/large.jpg",
            file_size=300,
            status="ready",
        )
        db.add_all([preview, small_block, large_block])
        db.commit()

        service = VisualEvidenceService(db)
        service.settings.vision_llm_max_images = 2
        service.settings.vision_llm_max_image_bytes = 1024
        evidence = make_evidence(page_index.id)
        enriched = service.enrich("10-PS-0101-3002-001流程是怎样的", [evidence], {"has_doc_code": True})

        assert [asset.asset_id for asset in enriched[0].assets] == [preview.id, large_block.id]
        assert enriched[0].assets[0].url == f"/api/documents/assets/{preview.id}"
    finally:
        db.close()


def test_llm_service_builds_multimodal_payload(tmp_path: Path, monkeypatch) -> None:
    """视觉证据回答应向 vision_llm 发送 OpenAI-compatible image_url 消息。"""

    db = make_session()
    try:
        image_path = tmp_path / "pid.png"
        image_path.write_bytes(b"\x89PNG\r\n\x1a\n")
        asset = DocumentAsset(
            document_id=11,
            version_no=1,
            page_id=1,
            asset_type=ASSET_TYPE_BLOCK_IMAGE,
            file_name="pid.png",
            mime_type="image/png",
            storage_backend="local",
            storage_path=str(image_path),
            file_size=image_path.stat().st_size,
            status="ready",
        )
        db.add(asset)
        db.commit()

        evidence = make_evidence()
        evidence.assets.append(
            EvidenceAsset(
                asset_id=asset.id,
                asset_type=asset.asset_type,
                url=f"/api/documents/assets/{asset.id}",
                mime_type=asset.mime_type,
                file_name=asset.file_name,
                file_size=asset.file_size,
                page_number=1,
                block_id=None,
            )
        )

        captured: dict[str, Any] = {}

        def fake_runtime_config(model_type: str, config=None) -> RuntimeModelConfig:  # noqa: ANN001
            assert model_type == "vision_llm"
            return RuntimeModelConfig(
                provider="qwen_api",
                model_name="qwen3.5-plus",
                api_base="https://example.test/v1",
                api_key="secret",
                model_type=model_type,
            )

        class FakeResponse:
            def raise_for_status(self) -> None:
                return None

            def json(self) -> dict[str, Any]:
                return {"choices": [{"message": {"content": "流程回答"}}]}

        def fake_post(url: str, headers: dict[str, str], json: dict[str, Any], timeout: int):  # noqa: A002
            captured["url"] = url
            captured["headers"] = headers
            captured["json"] = json
            captured["timeout"] = timeout
            return FakeResponse()

        service = LLMService(db)
        service.settings.vision_llm_max_images = 2
        service.settings.vision_llm_max_image_bytes = 1024
        monkeypatch.setattr(service, "_runtime_config", fake_runtime_config)
        monkeypatch.setattr("app.services.llm_service.requests.post", fake_post)

        answer = service.answer_with_multimodal_evidence("流程是怎样的", [evidence])

        assert answer == "流程回答"
        assert captured["json"]["model"] == "qwen3.5-plus"
        user_content = captured["json"]["messages"][1]["content"]
        assert user_content[0]["type"] == "text"
        assert user_content[1]["type"] == "image_url"
        assert user_content[1]["image_url"]["url"].startswith("data:image/png;base64,")
    finally:
        db.close()


def test_llm_service_streams_chunks(monkeypatch) -> None:
    """流式回答应逐段产出文本，并携带 stream 请求参数。"""

    db = make_session()
    try:
        evidence = make_evidence()
        captured: dict[str, Any] = {}

        def fake_runtime_config(model_type: str, config=None) -> RuntimeModelConfig:  # noqa: ANN001
            assert model_type == "llm"
            return RuntimeModelConfig(
                provider="qwen_api",
                model_name="qwen3.5-plus",
                api_base="https://example.test/v1",
                api_key="secret",
                model_type=model_type,
            )

        class FakeStreamResponse:
            def raise_for_status(self) -> None:
                return None

            def iter_lines(self, decode_unicode: bool = True):  # noqa: ARG002
                yield 'data: {"choices":[{"delta":{"content":"流式"}}]}'
                yield 'data: {"choices":[{"delta":{"content":"输出"}}]}'
                yield "data: [DONE]"

            def close(self) -> None:
                return None

        def fake_post(url: str, headers: dict[str, str], json: dict[str, Any], timeout: int, stream: bool = False):  # noqa: A002
            captured["url"] = url
            captured["headers"] = headers
            captured["json"] = json
            captured["timeout"] = timeout
            captured["stream"] = stream
            return FakeStreamResponse()

        service = LLMService(db)
        monkeypatch.setattr(service, "_runtime_config", fake_runtime_config)
        monkeypatch.setattr("app.services.llm_service.requests.post", fake_post)

        chunks = list(service.stream_answer_with_evidence("测试问题", [evidence]))

        assert chunks == ["流式", "输出"]
        assert captured["stream"] is True
        assert captured["json"]["stream"] is True
        assert captured["json"]["model"] == "qwen3.5-plus"
    finally:
        db.close()

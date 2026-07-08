"""
Retrieval Trace Service Tests

负责验证检索审计在持久化前会过滤项目元数据 evidence 使用的占位知识库 ID，
避免 metadata-only 证据写入 retrieval_traces 时触发外键约束异常。
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

BASE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE_DIR))

from app.retrieval.schemas import Evidence  # noqa: E402
from app.services.retrieval_trace_service import RetrievalTraceService  # noqa: E402


class DummyTraceRepository:
    """捕获待持久化 trace，避免测试依赖真实数据库。"""

    def __init__(self) -> None:
        self.added_trace = None

    def add(self, trace: Any) -> Any:
        self.added_trace = trace
        return trace


def make_service() -> tuple[RetrievalTraceService, DummyTraceRepository]:
    """构造仅保留核心依赖的 RetrievalTraceService 测试实例。"""

    repository = DummyTraceRepository()
    service = object.__new__(RetrievalTraceService)
    service.db = None
    service.settings = SimpleNamespace(retrieval_trace_enabled=True)
    service.repository = repository
    return service, repository


def test_record_chat_trace_normalizes_metadata_only_placeholder_knowledge_base_id() -> None:
    """纯项目元数据证据写审计轨迹时，应将 knowledge_base_id=0 归一化为 None。"""

    service, repository = make_service()
    evidence = Evidence(
        score=0.35,
        source_type="project_metadata",
        knowledge_base_id=0,
        project_id=2,
        document_id=0,
        chunk_id=2,
        drawing_no=None,
        file_name="项目基础信息",
        page_number=None,
        content="项目名称：西班牙LFP项目",
        retriever="project_metadata",
        metadata={"metadata_only": True},
    )

    trace = service.record_chat_trace(
        user=SimpleNamespace(id=1),
        session_id=8,
        message_id=17,
        question="这是什么项目？",
        chat_type="project_chat",
        mode="project_chat",
        project_id=2,
        raw={"intent": "project_qa"},
        evidences=[evidence],
        trace_steps=[{"elapsed_ms": 12}],
    )

    assert trace is repository.added_trace
    assert trace is not None
    assert trace.knowledge_base_id is None


def test_record_chat_trace_uses_first_valid_knowledge_base_id_from_evidences() -> None:
    """首条 evidence 是占位元数据时，应继续向后寻找可落库的真实知识库 ID。"""

    service, repository = make_service()
    metadata_evidence = Evidence(
        score=0.35,
        source_type="project_metadata",
        knowledge_base_id=0,
        project_id=2,
        document_id=0,
        chunk_id=2,
        drawing_no=None,
        file_name="项目基础信息",
        page_number=None,
        content="项目名称：西班牙LFP项目",
        retriever="project_metadata",
        metadata={"metadata_only": True},
    )
    document_evidence = Evidence(
        score=0.92,
        source_type="project",
        knowledge_base_id=9,
        project_id=2,
        document_id=3,
        chunk_id=4,
        drawing_no=None,
        file_name="项目周报.pdf",
        page_number=1,
        content="报告日期：2025/08/29",
        retriever="milvus",
    )

    trace = service.record_chat_trace(
        user=SimpleNamespace(id=1),
        session_id=8,
        message_id=17,
        question="这个项目最近进展如何？",
        chat_type="project_chat",
        mode="project_chat",
        project_id=2,
        raw={"intent": "project_qa"},
        evidences=[metadata_evidence, document_evidence],
        trace_steps=[{"elapsed_ms": 18}],
    )

    assert trace is repository.added_trace
    assert trace is not None
    assert trace.knowledge_base_id == 9

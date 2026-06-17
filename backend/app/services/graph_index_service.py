"""
Graph Index Service

负责：
1. 从 Chunk 中抽取第一阶段 GraphRAG 实体和关系
2. 将实体、关系写入 MySQL 图谱表并保留来源追踪
3. 支持后续替换为 Qwen graph_extractor 模型抽取
"""

from __future__ import annotations

import json
import logging
import re

from sqlalchemy.orm import Session

from app.models.document import Document, DocumentChunk
from app.models.graph import GraphEntity, GraphRelation
from app.repositories.document_repository import DocumentRepository
from app.repositories.graph_repository import GraphRepository

logger = logging.getLogger(__name__)

ENTITY_PATTERN = re.compile(r"[A-Za-z][A-Za-z0-9_.\-/]{2,}|[\u4e00-\u9fff]{2,12}")
STOP_WORDS = {"document", "page", "section", "content", "the", "and", "with"}


class GraphIndexService:
    """
    图谱索引服务

    职责：
    - 基于当前 Chunk 构建 staging 图谱
    - 保留 project_id/document_id/drawing_no/page_no/chunk_id 来源
    - 在发布阶段将 staging 图谱切换为 published
    """

    def __init__(self, db: Session) -> None:
        self.db = db
        self.document_repository = DocumentRepository(db)
        self.graph_repository = GraphRepository(db)

    def build_document_graph(self, document: Document) -> dict:
        """
        构建文档图谱。

        参数:
            document: 文档 ORM 对象。

        返回:
            图谱构建结果。
        """

        chunks = self.document_repository.list_chunks(document.id, version_no=document.version_no)
        self.graph_repository.clear_document_graph(document.id, document.version_no)
        entity_count = 0
        relation_count = 0
        for chunk in chunks:
            entities = self._extract_entities(document, chunk)
            saved_entities: list[GraphEntity] = []
            for payload in entities:
                saved_entities.append(self.graph_repository.add_entity(GraphEntity(**payload)))
                entity_count += 1
            relation_count += self._build_relations(document, chunk, saved_entities)
        logger.info("GraphRAG图谱构建完成: document_id=%s entities=%s relations=%s", document.id, entity_count, relation_count)
        return {"graph_entity_count": entity_count, "graph_relation_count": relation_count}

    def publish_document_graph(self, document: Document) -> dict:
        """
        发布文档图谱。

        参数:
            document: 文档 ORM 对象。

        返回:
            发布结果。
        """

        published_count = self.graph_repository.publish_document_graph(document.id, document.version_no)
        return {"published_graph_entity_count": published_count}

    def _extract_entities(self, document: Document, chunk: DocumentChunk) -> list[dict]:
        """
        规则抽取实体。

        说明：
            第一阶段先用确定性规则保证可运行；后续接入 Qwen graph_extractor 时，
            只需要替换该方法的抽取来源，实体落库结构保持不变。
        """

        candidates: list[str] = []
        for match in ENTITY_PATTERN.findall(chunk.content):
            token = match.strip(" ,.;:，。；：()（）[]【】")
            if len(token) < 2 or token.lower() in STOP_WORDS:
                continue
            candidates.append(token)
        unique_tokens = list(dict.fromkeys(candidates))[:8]
        entities: list[dict] = []
        for token in unique_tokens:
            entity_type = self._entity_type(token)
            entities.append(
                {
                    "knowledge_base_id": document.knowledge_base_id,
                    "project_id": document.project_id,
                    "document_id": document.id,
                    "chunk_id": chunk.id,
                    "version_no": document.version_no,
                    "drawing_no": document.drawing_no,
                    "page_number": chunk.page_number,
                    "entity_type": entity_type,
                    "entity_code": token if entity_type in {"equipment", "pipeline", "instrument", "code"} else None,
                    "entity_name": token,
                    "status": "staging",
                    "properties_json": json.dumps({"extractor": "rule_v1"}, ensure_ascii=False),
                }
            )
        return entities

    def _build_relations(self, document: Document, chunk: DocumentChunk, entities: list[GraphEntity]) -> int:
        """按 Chunk 内实体相邻关系构建弱关系。"""

        relation_count = 0
        for source, target in zip(entities, entities[1:], strict=False):
            self.graph_repository.add_relation(
                GraphRelation(
                    knowledge_base_id=document.knowledge_base_id,
                    project_id=document.project_id,
                    source_entity_id=source.id,
                    target_entity_id=target.id,
                    relation_type="co_occurs",
                    document_id=document.id,
                    chunk_id=chunk.id,
                    version_no=document.version_no,
                    drawing_no=document.drawing_no,
                    page_number=chunk.page_number,
                    status="staging",
                    properties_json=json.dumps({"extractor": "rule_v1"}, ensure_ascii=False),
                )
            )
            relation_count += 1
        return relation_count

    def _entity_type(self, token: str) -> str:
        """根据实体形态推断第一阶段实体类型。"""

        upper = token.upper()
        if re.match(r"^[A-Z]{1,4}-?\d", upper):
            return "equipment"
        if "管" in token or re.match(r"^[A-Z]{1,3}\d{2,}[-/]", upper):
            return "pipeline"
        if "仪" in token or upper.startswith(("PI", "TI", "FI", "LI")):
            return "instrument"
        if re.search(r"\d", token):
            return "code"
        return "term"

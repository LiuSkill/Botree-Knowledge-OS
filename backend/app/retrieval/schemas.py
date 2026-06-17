"""
Retrieval Internal Schemas

负责：
1. 定义内部检索证据结构
2. 在检索器、合并器、Agent 之间传递统一数据
3. 保留来源追踪字段
"""

from dataclasses import dataclass, field
from typing import Any


@dataclass
class EvidenceAsset:
    """
    检索证据关联的视觉资产。

    只保存可展示和可回源的安全元数据；图片二进制和 base64 只在调用视觉模型时临时读取。
    """

    asset_id: int
    asset_type: str
    url: str
    mime_type: str | None
    file_name: str
    file_size: int
    page_number: int | None
    block_id: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class Evidence:
    """
    检索证据

    职责：
    - 保存 Chunk 内容和文档来源
    - 保存检索得分，便于合并排序
    """

    score: float
    source_type: str
    knowledge_base_id: int
    project_id: int | None
    document_id: int
    chunk_id: int
    drawing_no: str | None
    file_name: str
    page_number: int | None
    content: str
    retriever: str
    metadata: dict[str, Any] = field(default_factory=dict)
    assets: list[EvidenceAsset] = field(default_factory=list)

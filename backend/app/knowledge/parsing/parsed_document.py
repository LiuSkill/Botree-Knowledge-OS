"""
Parsed Document Models

负责：
1. 为解析阶段提供结构化中间结果对象
2. 统一描述解析输入来源、页级内容和 MinerU 原始结果
3. 为资产持久化和预览接口提供稳定的数据契约
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class ParseSource:
    """
    解析输入来源

    职责：
    - 描述当前解析实际使用的文件路径
    - 记录是否经过 LibreOffice 转换
    - 为资产落库提供来源信息
    """

    source_path: str
    source_kind: str
    original_path: str
    converted_pdf_path: str | None = None
    document_id: int | None = None
    version_no: int | None = None
    mineru_output_host_dir: str | None = None
    mineru_output_container_dir: str | None = None
    mineru_content_list_path: str | None = None
    mineru_middle_json_path: str | None = None
    mineru_images_dir: str | None = None
    mineru_markdown_dir: str | None = None


@dataclass(slots=True)
class ParsedDocumentResult:
    """
    解析结果对象

    职责：
    - 承载统一页级结构
    - 保存原始解析响应，便于落库和排障
    - 暴露解析器名称和任务信息
    """

    pages: list[dict[str, Any]]
    parser_name: str
    parse_source: ParseSource
    raw_payload: dict[str, Any] | None = None
    task_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

"""结构感知的文档分块构建器。"""

from __future__ import annotations

import re

from app.knowledge.parsing.searchable_text import build_page_searchable_text, normalize_searchable_text


class ChunkBuilder:
    """优先沿业务结构边界分块，仅对超长结构块使用有界重叠窗口。"""

    def __init__(
        self,
        chunk_size: int = 800,
        overlap: int = 120,
        rule_version: str = "structure-v1",
        index_generation: str = "default",
    ) -> None:
        self.chunk_size = chunk_size
        self.overlap = overlap
        self.rule_version = rule_version
        self.index_generation = index_generation

    def build(self, pages: list[dict]) -> list[dict]:
        chunks: list[dict] = []
        for page in pages:
            raw_content = page.get("clean_content")
            content = str(raw_content) if isinstance(raw_content, str) and raw_content.strip() else build_page_searchable_text(page)
            if not content:
                continue
            for structural_block in self._structural_blocks(content):
                for chunk_text in self._bounded_parts(structural_block):
                    chunks.append(
                        {
                            "chunk_index": len(chunks) + 1,
                            "content": chunk_text,
                            "page_number": page.get("page_number"),
                            "section_title": self._guess_section_title(chunk_text),
                            "metadata": {
                                "chunk_rule_version": self.rule_version,
                                "index_generation": self.index_generation,
                            },
                        }
                    )
        for index, chunk in enumerate(chunks):
            chunk["metadata"]["previous_chunk_index"] = chunks[index - 1]["chunk_index"] if index > 0 else None
            chunk["metadata"]["next_chunk_index"] = chunks[index + 1]["chunk_index"] if index + 1 < len(chunks) else None
        return chunks

    def _structural_blocks(self, content: str) -> list[str]:
        return [normalize_searchable_text(part) for part in re.split(r"\n\s*\n+", content) if part.strip()]

    def _bounded_parts(self, block: str) -> list[str]:
        if len(block) <= self.chunk_size:
            return [block]
        parts: list[str] = []
        start = 0
        while start < len(block):
            end = min(start + self.chunk_size, len(block))
            part = block[start:end].strip()
            if part:
                parts.append(part)
            if end >= len(block):
                break
            start = max(end - self.overlap, start + 1)
        return parts

    def _normalize(self, text: str) -> str:
        return normalize_searchable_text(text)

    def _guess_section_title(self, text: str) -> str | None:
        first_line = text.split("\n", 1)[0].strip()
        return first_line if 0 < len(first_line) <= 80 else None

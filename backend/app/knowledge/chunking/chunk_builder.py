"""
Chunk Builder

负责：
1. 将解析文本切分为知识片段
2. 保留页码、章节和文档来源信息
3. 控制 Chunk 大小和 overlap
"""

from app.knowledge.parsing.searchable_text import build_page_searchable_text, normalize_searchable_text


class ChunkBuilder:
    """
    文档切块构建器

    职责：
    - 使用固定窗口切块
    - 避免过短碎片影响检索质量
    - MVP 阶段保持规则清晰可解释
    """

    def __init__(self, chunk_size: int = 800, overlap: int = 120) -> None:
        self.chunk_size = chunk_size
        self.overlap = overlap

    def build(self, pages: list[dict]) -> list[dict]:
        """
        生成 Chunk 数据

        参数:
            pages: 页面文本列表

        返回:
            Chunk 字典列表。
        """

        chunks: list[dict] = []
        for page in pages:
            content = build_page_searchable_text(page)
            page_number = page.get("page_number")
            if not content:
                continue

            # 固定窗口切分并保留 overlap，确保跨段上下文不会被完全切断。
            start = 0
            while start < len(content):
                end = min(start + self.chunk_size, len(content))
                chunk_text = content[start:end].strip()
                if chunk_text:
                    chunks.append(
                        {
                            "chunk_index": len(chunks) + 1,
                            "content": chunk_text,
                            "page_number": page_number,
                            "section_title": self._guess_section_title(chunk_text),
                        }
                    )
                if end >= len(content):
                    break
                start = max(end - self.overlap, start + 1)
        return chunks

    def _normalize(self, text: str) -> str:
        """清理文本中的多余空白。"""

        return normalize_searchable_text(text)

    def _guess_section_title(self, text: str) -> str | None:
        """从 Chunk 开头推断章节标题。"""

        first_line = text.split("\n", 1)[0].strip()
        if 0 < len(first_line) <= 80:
            return first_line
        return None

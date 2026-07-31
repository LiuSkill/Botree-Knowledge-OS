"""
导出真实解析链路生成的 chunk 预览。

职责：
1. 走 ParserService -> ParsedContentCleaner -> ChunkBuilder 的真实链路
2. 将 chunk 以 Markdown 形式落盘，便于人工核对
3. 在解析失败时输出清晰错误报告，避免旧快照与真实结果混淆
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

PROJECT_BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_BACKEND_ROOT))

from app.core.exceptions import AppException
from app.knowledge.chunking.chunk_builder import ChunkBuilder
from app.knowledge.parsing.parsed_content_cleaner import ParsedContentCleaner
from app.knowledge.parsing.parser_service import ParserService


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="导出真实解析链路的 chunk 预览")
    parser.add_argument("--input", required=True, help="待处理文件路径")
    parser.add_argument("--output", required=True, help="Markdown 输出路径")
    parser.add_argument("--document-title", help="覆盖 chunk 第一行使用的文档标题")
    parser.add_argument("--file-name", help="覆盖文档文件名元信息")
    parser.add_argument("--write-error-report", action="store_true", help="解析失败时写出错误报告而不是直接退出")
    return parser.parse_args()


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _render_chunk_markdown(
    *,
    input_path: Path,
    output_path: Path,
    document_title: str,
    file_name: str,
    parser_name: str,
    task_id: str | None,
    pages: list[dict],
    chunks: list[dict],
    cleaning_summary: dict[str, object],
) -> str:
    generated_at = datetime.now().isoformat(timespec="seconds")
    lines: list[str] = [
        "# Live chunk export",
        "",
        f"- Generated at: {generated_at}",
        f"- Source file: `{input_path}`",
        f"- Output file: `{output_path}`",
        f"- Document title: `{document_title}`",
        f"- File name metadata: `{file_name}`",
        f"- Parser: `{parser_name}`",
        f"- Task ID: `{task_id or 'N/A'}`",
        f"- Page count: `{len(pages)}`",
        f"- Chunk count: `{len(chunks)}`",
        f"- Chunk window: `800 chars`",
        f"- Metadata prefix in chunk body: `{document_title}`",
        f"- Cleaning summary: `{cleaning_summary}`",
        "",
    ]

    for chunk in chunks:
        page_numbers = chunk.get("metadata", {}).get("page_numbers") or []
        page_label = ",".join(str(item) for item in page_numbers) if page_numbers else str(chunk.get("page_number") or "N/A")
        lines.extend(
            [
                f"## CHUNK {chunk['chunk_index']} | {len(chunk['content'])} chars | pages {page_label}",
                "",
                "```text",
                str(chunk["content"]),
                "```",
                "",
            ]
        )
    return "\n".join(lines).strip() + "\n"


def _render_error_markdown(
    *,
    input_path: Path,
    output_path: Path,
    document_title: str,
    file_name: str,
    error_message: str,
) -> str:
    generated_at = datetime.now().isoformat(timespec="seconds")
    return (
        "# Live chunk export error\n\n"
        f"- Generated at: {generated_at}\n"
        f"- Source file: `{input_path}`\n"
        f"- Output file: `{output_path}`\n"
        f"- Document title: `{document_title}`\n"
        f"- File name metadata: `{file_name}`\n"
        f"- Error: `{error_message}`\n"
    )


def main() -> int:
    args = parse_args()
    input_path = Path(args.input).expanduser().resolve()
    output_path = Path(args.output).expanduser().resolve()
    document_title = args.document_title or input_path.stem
    file_name = args.file_name or input_path.name

    try:
        parsed_result = ParserService().parse_document(str(input_path))
        parsed_result = ParsedContentCleaner().clean_result(parsed_result)
        chunks = ChunkBuilder().build(
            parsed_result.pages,
            document_metadata={
                "document_title": document_title,
                "file_name": file_name,
            },
        )
    except AppException as exc:
        if not args.write_error_report:
            raise
        error_markdown = _render_error_markdown(
            input_path=input_path,
            output_path=output_path,
            document_title=document_title,
            file_name=file_name,
            error_message=str(exc),
        )
        _write_text(output_path, error_markdown)
        print(f"error_report={output_path}")
        return 0

    markdown = _render_chunk_markdown(
        input_path=input_path,
        output_path=output_path,
        document_title=document_title,
        file_name=file_name,
        parser_name=parsed_result.parser_name,
        task_id=parsed_result.task_id,
        pages=parsed_result.pages,
        chunks=chunks,
        cleaning_summary=dict(parsed_result.metadata.get("content_cleaning", {})),
    )
    _write_text(output_path, markdown)
    print(f"chunk_report={output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

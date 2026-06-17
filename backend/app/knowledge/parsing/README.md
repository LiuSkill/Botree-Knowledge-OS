## Parsing Module

负责：
1. 根据部署配置选择 MinerU、本地解析器或 LibreOffice 转 PDF 链路
2. 在配置 MinerU 时强制走 `/tasks` 异步解析链路
3. 将解析结果统一输出为页级文本结构，供 PageIndex、ChunkBuilder 和原始内容预览使用

调用关系：
`DocumentService._parse_to_chunks()` -> `ParserService.parse_document()` -> `LibreOfficeConversionService` -> `MinerUParser` 或 `SimpleTextParser`

输入：
- `storage_path`：本地真实文件路径
- `document_id/version_no`：Office 转 PDF 缓存、派生资产和版本级复用所需上下文

输出：
- 标准化解析结果 `ParsedDocumentResult`
- 兼容旧链路时仍可通过 `parse()` 取得 `list[dict]`
- 页级结果至少包含 `page_number`、`content`、`blocks`

当前策略：
- `pdf` 直接进入 MinerU
- `doc/docx/ppt/pptx/xls/xlsx/odt/odp/ods/rtf` 先经 LibreOffice 转 PDF，再进入 MinerU
- `txt/md/csv` 继续走本地简单解析器
- 配置 `MINERU_BASE_URL` 后，非简单文本解析阶段必须由 MinerU 成功完成
- MinerU 使用 `POST /tasks` -> `GET /tasks/{task_id}` -> `GET /tasks/{task_id}/result`
- 总等待预算固定为 `MINERU_TASK_TIMEOUT_SECONDS=300`
- 单次 HTTP 超时使用 `MINERU_HTTP_TIMEOUT_SECONDS=30`
- 轮询间隔使用 `MINERU_POLL_INTERVAL_SECONDS=5`
- LibreOffice 转换配置使用 `LIBREOFFICE_BINARY`、`LIBREOFFICE_TIMEOUT_SECONDS`、`LIBREOFFICE_WORK_DIR`
- 同一文档版本的转换 PDF 会按 `document_id/version_no` 复用，避免重复转换
- 只有在未配置 `MINERU_BASE_URL` 时，才允许 `SimpleTextParser` 作为本地兜底
- MinerU 超时、失败、取消或结果异常时，文档构建与索引任务都必须失败
- MinerU 原始 JSON、转换 PDF、页预览图和块图片会落库到 `document_assets`，供文档详情页预览

示例：
```python
from app.knowledge.parsing.parser_service import ParserService

result = ParserService().parse_document("storage/uploads/example.docx", document_id=12, version_no=3)
assert result.pages[0]["page_number"] == 1
assert "content" in result.pages[0]
assert result.parse_source.source_kind in {"original", "converted_pdf"}
```

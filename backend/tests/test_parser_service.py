"""
Parser Service Tests

负责：
1. 验证 MinerU `/tasks` 异步解析链路
2. 验证配置 MinerU 后不再回退本地解析器
3. 验证 Office 转 PDF、共享卷图片路径映射和转换缓存复用
"""

from __future__ import annotations

import json
import logging
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch

BASE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE_DIR))

from app.core.exceptions import AppException  # noqa: E402
from app.knowledge.parsing.mineru_parser import MinerUParser  # noqa: E402
from app.knowledge.parsing.parsed_document import ParseSource, ParsedDocumentResult  # noqa: E402
from app.knowledge.parsing.parser_service import ParserService  # noqa: E402
from app.knowledge.parsing.simple_text_parser import SimpleTextParser  # noqa: E402
from app.services.document_asset_service import DocumentAssetService  # noqa: E402
from app.services.libreoffice_conversion_service import LibreOfficeConversionResult, LibreOfficeConversionService  # noqa: E402

logger = logging.getLogger(__name__)


class FakeResponse:
    """
    测试用 HTTP 响应对象。

    职责：
    - 模拟 requests.Response 的最小行为
    - 支持 2xx、4xx/5xx 和 JSON 返回值
    """

    def __init__(self, status_code: int, payload: dict, text: str | None = None) -> None:
        self.status_code = status_code
        self._payload = payload
        self.text = text or ""

    def raise_for_status(self) -> None:
        """
        在 4xx/5xx 场景下模拟 requests 的 HTTPError。
        """

        if self.status_code >= 400:
            import requests

            raise requests.HTTPError(f"HTTP {self.status_code}", response=self)

    def json(self) -> dict:
        """
        返回预设 JSON 载荷。

        返回:
            预设字典
        """

        return self._payload


def with_temp_file(suffix: str, content: bytes) -> str:
    """
    创建临时文件并返回路径。

    参数:
        suffix: 文件后缀
        content: 文件内容

    返回:
        临时文件绝对路径
    """

    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as file_obj:
        file_obj.write(content)
        return file_obj.name


def test_mineru_parser_runs_async_task_and_extracts_page_blocks() -> None:
    """
    MinerUParser 必须走 `/tasks` 链路，并把 content_list 聚合为页级结构。
    """

    parser = MinerUParser()
    original_base_url = parser.settings.mineru_base_url
    original_timeout = parser.settings.mineru_task_timeout_seconds
    original_poll_interval = parser.settings.mineru_poll_interval_seconds
    original_http_timeout = parser.settings.mineru_http_timeout_seconds
    original_output_host_dir = parser.settings.mineru_output_host_dir
    original_output_container_dir = parser.settings.mineru_output_container_dir
    parser.settings.mineru_base_url = "http://127.0.0.1:8000"
    parser.settings.mineru_task_timeout_seconds = 300
    parser.settings.mineru_poll_interval_seconds = 1
    parser.settings.mineru_http_timeout_seconds = 30
    parser.settings.mineru_output_container_dir = "/data/mineru-output"
    temp_path = with_temp_file(".pdf", b"%PDF-1.5 test")

    try:
        with tempfile.TemporaryDirectory() as output_dir:
            parser.settings.mineru_output_host_dir = output_dir
            (Path(output_dir) / "task-1").mkdir(parents=True, exist_ok=True)

            with patch(
                "app.knowledge.parsing.mineru_parser.requests.post",
                return_value=FakeResponse(202, {"task_id": "task-1", "status": "pending"}),
            ) as mocked_post:
                with patch(
                    "app.knowledge.parsing.mineru_parser.requests.get",
                    side_effect=[
                        FakeResponse(200, {"task_id": "task-1", "status": "processing", "queued_ahead": 0}),
                        FakeResponse(200, {"task_id": "task-1", "status": "completed", "queued_ahead": 0}),
                        FakeResponse(
                            200,
                            {
                                "results": {
                                    "demo.pdf": {
                                        "content_list": (
                                            '[{"text":"第一页A","page_idx":0},'
                                            '{"text":"第一页B","page_idx":0},'
                                            '{"text":"第二页","page_idx":1}]'
                                        )
                                    }
                                }
                            },
                        ),
                    ],
                ):
                    with patch.object(parser, "_sleep_seconds", return_value=None):
                        pages = parser.parse(temp_path)

        assert [page["page_number"] for page in pages] == [1, 2]
        assert pages[0]["content"] == "第一页A\n第一页B"
        assert len(pages[0]["blocks"]) == 2
        assert pages[0]["blocks"][0]["block_type"] == "text"
        kwargs = mocked_post.call_args.kwargs
        assert kwargs["files"][0][0] == "files"
        assert kwargs["files"][0][1][0] == Path(temp_path).name
        assert kwargs["data"]["return_md"] == "true"
        assert kwargs["data"]["return_content_list"] == "true"
        assert kwargs["data"]["return_middle_json"] == "true"
        assert kwargs["data"]["return_images"] == "true"
        assert kwargs["data"]["output_dir"] == "/data/mineru-output"
    finally:
        parser.settings.mineru_base_url = original_base_url
        parser.settings.mineru_task_timeout_seconds = original_timeout
        parser.settings.mineru_poll_interval_seconds = original_poll_interval
        parser.settings.mineru_http_timeout_seconds = original_http_timeout
        parser.settings.mineru_output_host_dir = original_output_host_dir
        parser.settings.mineru_output_container_dir = original_output_container_dir
        Path(temp_path).unlink(missing_ok=True)


def test_mineru_parser_resolves_relative_image_paths_from_shared_volume() -> None:
    """
    MinerU 返回相对图片路径时，必须按共享卷任务目录映射到宿主机路径。
    """

    parser = MinerUParser()
    original_base_url = parser.settings.mineru_base_url
    original_output_host_dir = parser.settings.mineru_output_host_dir
    original_output_container_dir = parser.settings.mineru_output_container_dir
    parser.settings.mineru_base_url = "http://127.0.0.1:8000"
    parser.settings.mineru_output_container_dir = "/data/mineru-output"
    temp_path = with_temp_file(".pdf", b"%PDF-1.5 image-path")

    try:
        with tempfile.TemporaryDirectory() as output_dir:
            parser.settings.mineru_output_host_dir = output_dir
            task_output_dir = Path(output_dir) / "task-image"
            images_dir = task_output_dir / "images"
            images_dir.mkdir(parents=True, exist_ok=True)
            (images_dir / "demo.jpg").write_bytes(b"fake-image")
            (task_output_dir / "content_list.json").write_text("[]", encoding="utf-8")
            (task_output_dir / "middle.json").write_text("{}", encoding="utf-8")

            with patch(
                "app.knowledge.parsing.mineru_parser.requests.post",
                return_value=FakeResponse(202, {"task_id": "task-image", "status": "pending"}),
            ):
                with patch(
                    "app.knowledge.parsing.mineru_parser.requests.get",
                    side_effect=[
                        FakeResponse(200, {"task_id": "task-image", "status": "completed", "queued_ahead": 0}),
                        FakeResponse(
                            200,
                            {
                                "results": {
                                    "demo.pdf": {
                                        "content_list": json.dumps(
                                            [
                                                {"text": "第一页文本", "page_idx": 0},
                                                {
                                                    "type": "image",
                                                    "text": "图片说明",
                                                    "img_path": "images/demo.jpg",
                                                    "page_idx": 0,
                                                },
                                            ],
                                            ensure_ascii=False,
                                        )
                                    }
                                }
                            },
                        ),
                    ],
                ):
                    with patch.object(parser, "_sleep_seconds", return_value=None):
                        result = parser.parse_document(temp_path)

        assert result.task_id == "task-image"
        assert result.parse_source.mineru_output_host_dir == str(task_output_dir)
        assert result.parse_source.mineru_content_list_path == str(task_output_dir / "content_list.json")
        assert result.parse_source.mineru_middle_json_path == str(task_output_dir / "middle.json")
        assert result.parse_source.mineru_images_dir == str(images_dir)
        image_candidate = result.pages[0]["blocks"][1]["image_candidates"][0]
        assert image_candidate["local_path"] == "images/demo.jpg"
        assert image_candidate["resolution_status"] == "relative_to_output_dir"
        assert image_candidate["resolved_local_path"] == str(images_dir / "demo.jpg")
    finally:
        parser.settings.mineru_base_url = original_base_url
        parser.settings.mineru_output_host_dir = original_output_host_dir
        parser.settings.mineru_output_container_dir = original_output_container_dir
        Path(temp_path).unlink(missing_ok=True)


def test_mineru_parser_binds_inline_images_from_result_payload() -> None:
    """
    当 MinerU 只在结果 JSON 顶层返回内联图片时，解析器也必须把图片回填到候选对象。
    """

    parser = MinerUParser()
    original_base_url = parser.settings.mineru_base_url
    original_output_host_dir = parser.settings.mineru_output_host_dir
    original_output_container_dir = parser.settings.mineru_output_container_dir
    parser.settings.mineru_base_url = "http://127.0.0.1:8000"
    parser.settings.mineru_output_container_dir = "/workspace/output"
    temp_path = with_temp_file(".pdf", b"%PDF-1.5 inline-image")

    try:
        with tempfile.TemporaryDirectory() as output_dir:
            parser.settings.mineru_output_host_dir = output_dir
            task_output_dir = Path(output_dir) / "task-inline"
            task_output_dir.mkdir(parents=True, exist_ok=True)

            with patch(
                "app.knowledge.parsing.mineru_parser.requests.post",
                return_value=FakeResponse(202, {"task_id": "task-inline", "status": "pending"}),
            ):
                with patch(
                    "app.knowledge.parsing.mineru_parser.requests.get",
                    side_effect=[
                        FakeResponse(200, {"task_id": "task-inline", "status": "completed", "queued_ahead": 0}),
                        FakeResponse(
                            200,
                            {
                                "results": {
                                    "demo.pdf": {
                                        "content_list": json.dumps(
                                            [
                                                {
                                                    "type": "image",
                                                    "text": "内联图片",
                                                    "img_path": "images/demo-inline.jpg",
                                                    "page_idx": 0,
                                                }
                                            ],
                                            ensure_ascii=False,
                                        ),
                                        "images": {
                                            "demo-inline.jpg": "data:image/jpeg;base64,ZmFrZS1pbmxpbmU=",
                                        },
                                    }
                                }
                            },
                        ),
                    ],
                ):
                    with patch.object(parser, "_sleep_seconds", return_value=None):
                        result = parser.parse_document(temp_path)

        image_candidate = result.pages[0]["blocks"][0]["image_candidates"][0]
        assert image_candidate["local_path"] == "images/demo-inline.jpg"
        assert image_candidate["payload_source"] == "mineru_result_images"
        assert image_candidate["inline_payload_key"] in {"demo-inline.jpg", "images/demo-inline.jpg"}
        assert image_candidate["payload_base64"] == "data:image/jpeg;base64,ZmFrZS1pbmxpbmU="
    finally:
        parser.settings.mineru_base_url = original_base_url
        parser.settings.mineru_output_host_dir = original_output_host_dir
        parser.settings.mineru_output_container_dir = original_output_container_dir
        Path(temp_path).unlink(missing_ok=True)


def test_mineru_parser_prepares_output_root_without_new_settings_method() -> None:
    """
    运行时拿到旧版 Settings 对象时，也不能因为缺少输出目录校验方法而失败。
    """

    class LegacySettings:
        """
        测试用旧配置对象，只保留基础字段。
        """

        mineru_output_container_dir = "/workspace/output"

        def __init__(self, output_dir: str) -> None:
            self.mineru_output_host_dir = output_dir

        def resolve_local_path(self, path_value: str) -> Path:
            """
            模拟 Settings.resolve_local_path 的最小行为。
            """

            return Path(path_value)

    parser = object.__new__(MinerUParser)
    with tempfile.TemporaryDirectory() as output_dir:
        parser.settings = LegacySettings(output_dir)
        prepared_path = parser._prepare_output_root()
        assert prepared_path.is_dir()

    assert prepared_path.name


def test_mineru_parser_maps_container_absolute_paths_to_host_paths() -> None:
    """
    MinerU 返回容器内绝对路径时，必须映射到宿主机共享卷路径。
    """

    parser = MinerUParser()
    original_base_url = parser.settings.mineru_base_url
    original_output_host_dir = parser.settings.mineru_output_host_dir
    original_output_container_dir = parser.settings.mineru_output_container_dir
    parser.settings.mineru_base_url = "http://127.0.0.1:8000"
    parser.settings.mineru_output_container_dir = "/data/mineru-output"
    temp_path = with_temp_file(".pdf", b"%PDF-1.5 absolute-image-path")

    try:
        with tempfile.TemporaryDirectory() as output_dir:
            parser.settings.mineru_output_host_dir = output_dir
            task_output_dir = Path(output_dir) / "task-abs"
            images_dir = task_output_dir / "images"
            images_dir.mkdir(parents=True, exist_ok=True)
            absolute_candidate_path = "/data/mineru-output/task-abs/images/demo-abs.jpg"
            (images_dir / "demo-abs.jpg").write_bytes(b"fake-image")

            with patch(
                "app.knowledge.parsing.mineru_parser.requests.post",
                return_value=FakeResponse(202, {"task_id": "task-abs", "status": "pending"}),
            ):
                with patch(
                    "app.knowledge.parsing.mineru_parser.requests.get",
                    side_effect=[
                        FakeResponse(200, {"task_id": "task-abs", "status": "completed", "queued_ahead": 0}),
                        FakeResponse(
                            200,
                            {
                                "results": {
                                    "demo.pdf": {
                                        "content_list": json.dumps(
                                            [
                                                {
                                                    "type": "image",
                                                    "text": "绝对路径图片",
                                                    "img_path": absolute_candidate_path,
                                                    "page_idx": 0,
                                                }
                                            ],
                                            ensure_ascii=False,
                                        )
                                    }
                                }
                            },
                        ),
                    ],
                ):
                    with patch.object(parser, "_sleep_seconds", return_value=None):
                        result = parser.parse_document(temp_path)

        image_candidate = result.pages[0]["blocks"][0]["image_candidates"][0]
        assert image_candidate["local_path"] == absolute_candidate_path
        assert image_candidate["resolution_status"] == "container_path_mapped"
        assert image_candidate["resolved_local_path"] == str(images_dir / "demo-abs.jpg")
    finally:
        parser.settings.mineru_base_url = original_base_url
        parser.settings.mineru_output_host_dir = original_output_host_dir
        parser.settings.mineru_output_container_dir = original_output_container_dir
        Path(temp_path).unlink(missing_ok=True)


def test_mineru_parser_times_out_with_task_id() -> None:
    """
    MinerU 长时间无结果时，必须抛出带 task_id 的超时异常。
    """

    parser = MinerUParser()
    original_base_url = parser.settings.mineru_base_url
    original_timeout = parser.settings.mineru_task_timeout_seconds
    original_poll_interval = parser.settings.mineru_poll_interval_seconds
    parser.settings.mineru_base_url = "http://127.0.0.1:8000"
    parser.settings.mineru_task_timeout_seconds = 2
    parser.settings.mineru_poll_interval_seconds = 1
    temp_path = with_temp_file(".pdf", b"%PDF-1.5 timeout")

    try:
        with patch(
            "app.knowledge.parsing.mineru_parser.requests.post",
            return_value=FakeResponse(202, {"task_id": "task-timeout", "status": "pending"}),
        ):
            with patch(
                "app.knowledge.parsing.mineru_parser.requests.get",
                return_value=FakeResponse(200, {"task_id": "task-timeout", "status": "processing", "queued_ahead": 0}),
            ):
                with patch.object(parser, "_sleep_seconds", return_value=None):
                    with patch.object(parser, "_current_monotonic", side_effect=[0.0, 0.0, 3.0]):
                        try:
                            parser.parse(temp_path)
                            raise AssertionError("MinerU 超时场景应抛出 AppException")
                        except AppException as exc:
                            assert "task-timeout" in str(exc)
                            assert "超时" in str(exc)
    finally:
        parser.settings.mineru_base_url = original_base_url
        parser.settings.mineru_task_timeout_seconds = original_timeout
        parser.settings.mineru_poll_interval_seconds = original_poll_interval
        Path(temp_path).unlink(missing_ok=True)


def test_mineru_parser_raises_when_task_failed() -> None:
    """
    MinerU 返回 failed/canceled 时必须直接失败。
    """

    parser = MinerUParser()
    original_base_url = parser.settings.mineru_base_url
    parser.settings.mineru_base_url = "http://127.0.0.1:8000"
    temp_path = with_temp_file(".pdf", b"%PDF-1.5 failed")

    try:
        with patch(
            "app.knowledge.parsing.mineru_parser.requests.post",
            return_value=FakeResponse(202, {"task_id": "task-failed", "status": "pending"}),
        ):
            with patch(
                "app.knowledge.parsing.mineru_parser.requests.get",
                return_value=FakeResponse(200, {"task_id": "task-failed", "status": "failed", "error": "bad file"}),
            ):
                with patch.object(parser, "_sleep_seconds", return_value=None):
                    try:
                        parser.parse(temp_path)
                        raise AssertionError("MinerU failed 场景应抛出 AppException")
                    except AppException as exc:
                        assert "task-failed" in str(exc)
                        assert "bad file" in str(exc)
    finally:
        parser.settings.mineru_base_url = original_base_url
        Path(temp_path).unlink(missing_ok=True)


def test_parser_service_does_not_fallback_when_mineru_is_configured() -> None:
    """
    配置 MinerU 后，PDF 运行时失败不得回退本地解析器。
    """

    service = ParserService()
    original_base_url = service.settings.mineru_base_url
    service.settings.mineru_base_url = "http://127.0.0.1:8000"
    temp_path = with_temp_file(".pdf", b"%PDF-1.5 no fallback")

    try:
        mocked_simple_parse = Mock(return_value=[{"page_number": 1, "content": "fallback content"}])
        with patch.object(service.mineru_parser, "parse_document", side_effect=AppException("MinerU失败", status_code=502)):
            with patch.object(service.simple_parser, "parse", mocked_simple_parse):
                try:
                    service.parse_document(temp_path)
                    raise AssertionError("配置 MinerU 后不应回退本地解析器")
                except AppException as exc:
                    assert "MinerU失败" in str(exc)
        mocked_simple_parse.assert_not_called()
    finally:
        service.settings.mineru_base_url = original_base_url
        Path(temp_path).unlink(missing_ok=True)


def test_parser_service_uses_simple_parser_when_mineru_is_unconfigured() -> None:
    """
    未配置 MinerU 时，PDF 应回退本地解析器。
    """

    service = ParserService()
    original_base_url = service.settings.mineru_base_url
    service.settings.mineru_base_url = ""
    temp_path = with_temp_file(".pdf", b"%PDF-1.5 local parser")

    try:
        mocked_simple_parse = Mock(return_value=[{"page_number": 1, "content": "local content"}])
        with patch.object(service.simple_parser, "parse", mocked_simple_parse):
            result = service.parse_document(temp_path)
        assert result.pages == [{"page_number": 1, "content": "local content"}]
        mocked_simple_parse.assert_called_once_with(temp_path)
    finally:
        service.settings.mineru_base_url = original_base_url
        Path(temp_path).unlink(missing_ok=True)


def test_parser_service_converts_office_before_mineru() -> None:
    """
    Office 文档必须先转 PDF，再把转换结果交给 MinerU。
    """

    service = ParserService()
    original_base_url = service.settings.mineru_base_url
    service.settings.mineru_base_url = "http://127.0.0.1:8000"
    temp_path = with_temp_file(".docx", b"fake-docx")
    converted_pdf = with_temp_file(".pdf", b"%PDF-1.5 converted")
    parse_result = ParsedDocumentResult(
        pages=[{"page_number": 1, "content": "converted content"}],
        parser_name="mineru",
        parse_source=ParseSource(
            source_path=converted_pdf,
            source_kind="converted_pdf",
            original_path=temp_path,
            converted_pdf_path=converted_pdf,
        ),
        raw_payload={"task_id": "demo"},
        task_id="demo",
        metadata={},
    )

    try:
        with patch.object(
            service.libreoffice_service,
            "convert",
            return_value=LibreOfficeConversionResult(pdf_path=converted_pdf, reused=False, source_path=temp_path),
        ) as mocked_convert:
            with patch.object(service.mineru_parser, "parse_document", return_value=parse_result) as mocked_parse:
                result = service.parse_document(temp_path, document_id=9, version_no=3)

        assert result.pages[0]["content"] == "converted content"
        mocked_convert.assert_called_once_with(storage_path=temp_path, document_id=9, version_no=3)
        mocked_parse.assert_called_once()
        assert mocked_parse.call_args.args[0] == converted_pdf
        assert mocked_parse.call_args.kwargs["parse_source"].source_kind == "converted_pdf"
    finally:
        service.settings.mineru_base_url = original_base_url
        Path(temp_path).unlink(missing_ok=True)
        Path(converted_pdf).unlink(missing_ok=True)


def test_libreoffice_conversion_service_reuses_existing_pdf() -> None:
    """
    同一文档版本存在转换 PDF 时，应复用缓存而不是再次调��� CLI。
    """

    service = LibreOfficeConversionService()
    original_work_dir = service.settings.libreoffice_work_dir
    source_path = with_temp_file(".pptx", b"fake-pptx")

    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            service.settings.libreoffice_work_dir = temp_dir
            output_dir = Path(temp_dir) / "8" / "v2" / "converted"
            output_dir.mkdir(parents=True, exist_ok=True)
            output_pdf = output_dir / f"{Path(source_path).stem}.pdf"
            output_pdf.write_bytes(b"%PDF-1.5 cached")

            with patch.object(service, "_resolve_binary", return_value="soffice"):
                with patch.object(service, "_run_command") as mocked_run:
                    result = service.convert(source_path, document_id=8, version_no=2)

            assert result.reused is True
            assert result.pdf_path == str(output_pdf)
            mocked_run.assert_not_called()
    finally:
        service.settings.libreoffice_work_dir = original_work_dir
        Path(source_path).unlink(missing_ok=True)


def test_libreoffice_conversion_service_uses_isolated_profile_and_cleans_it() -> None:
    """
    LibreOffice 转换必须使用独立 profile，避免卡死实例污染后续任务。
    """

    service = LibreOfficeConversionService()
    original_work_dir = service.settings.libreoffice_work_dir
    source_path = with_temp_file(".docx", b"fake-docx")
    captured: dict[str, object] = {}

    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            service.settings.libreoffice_work_dir = temp_dir

            def fake_run(command: list[str], timeout_seconds: int) -> subprocess.CompletedProcess[str]:
                captured["command"] = command
                captured["timeout_seconds"] = timeout_seconds
                profile_arg = next(arg for arg in command if arg.startswith("-env:UserInstallation=file://"))
                profile_path = Path(profile_arg.removeprefix("-env:UserInstallation=file://"))
                captured["profile_path"] = profile_path
                assert profile_path.exists()

                output_dir = Path(command[command.index("--outdir") + 1])
                output_pdf = output_dir / f"{Path(source_path).stem}.pdf"
                output_pdf.write_bytes(b"%PDF-1.5 converted")
                return subprocess.CompletedProcess(command, 0, "", "")

            with patch.object(service, "_resolve_binary", return_value="soffice"):
                with patch.object(service, "_run_command", side_effect=fake_run):
                    result = service.convert(source_path, document_id=12, version_no=4)

            command = captured["command"]
            assert isinstance(command, list)
            assert result.reused is False
            assert result.pdf_path.endswith(".pdf")
            assert captured["timeout_seconds"] == service.settings.libreoffice_timeout_seconds
            assert "--nolockcheck" in command
            assert "--norestore" in command
            assert not Path(captured["profile_path"]).exists()
    finally:
        service.settings.libreoffice_work_dir = original_work_dir
        Path(source_path).unlink(missing_ok=True)


def test_libreoffice_run_command_terminates_process_group_on_timeout() -> None:
    """
    底层 soffice 超时时必须终止整个进程组，避免残留 soffice.bin。
    """

    service = LibreOfficeConversionService()
    process = Mock()
    process.communicate.side_effect = subprocess.TimeoutExpired(["soffice"], 1)
    process.pid = 12345

    with patch("app.services.libreoffice_conversion_service.subprocess.Popen", return_value=process) as mocked_popen:
        with patch.object(service, "_terminate_process_tree") as mocked_terminate:
            try:
                service._run_command(["soffice"], timeout_seconds=1)
                raise AssertionError("LibreOffice 超时应继续抛出 TimeoutExpired")
            except subprocess.TimeoutExpired:
                pass

    mocked_terminate.assert_called_once_with(process)
    assert mocked_popen.call_args.kwargs["shell"] is False
    assert mocked_popen.call_args.kwargs["text"] is True


def test_document_asset_service_accepts_inline_image_payload() -> None:
    """
    只有内联 base64 图片时，不应再被统计为“图片路径缺失”。
    """

    service = object.__new__(DocumentAssetService)
    candidate = {
        "local_path": "images/demo-inline.jpg",
        "payload_base64": "data:image/jpeg;base64,ZmFrZS1hc3NldA==",
    }

    assert service._candidate_path_missing(candidate) is False


def test_simple_text_parser_rejects_invalid_pdf_header() -> None:
    """
    损坏 PDF 必须返回明确错误，而不是误判为解析服务故障。
    """

    parser = SimpleTextParser()
    temp_path = with_temp_file(".pdf", b"\x88}\x1c\x98\x04\x01\x05\x00")
    try:
        try:
            parser.parse(temp_path)
            raise AssertionError("损坏 PDF 应抛出 AppException")
        except AppException as exc:
            assert "PDF文件头无效" in str(exc)
    finally:
        Path(temp_path).unlink(missing_ok=True)


def main() -> None:
    """
    执行轻量解析单元测试。
    """

    test_mineru_parser_runs_async_task_and_extracts_page_blocks()
    test_mineru_parser_resolves_relative_image_paths_from_shared_volume()
    test_mineru_parser_binds_inline_images_from_result_payload()
    test_mineru_parser_prepares_output_root_without_new_settings_method()
    test_mineru_parser_maps_container_absolute_paths_to_host_paths()
    test_mineru_parser_times_out_with_task_id()
    test_mineru_parser_raises_when_task_failed()
    test_parser_service_does_not_fallback_when_mineru_is_configured()
    test_parser_service_uses_simple_parser_when_mineru_is_unconfigured()
    test_parser_service_converts_office_before_mineru()
    test_libreoffice_conversion_service_reuses_existing_pdf()
    test_libreoffice_conversion_service_uses_isolated_profile_and_cleans_it()
    test_libreoffice_run_command_terminates_process_group_on_timeout()
    test_document_asset_service_accepts_inline_image_payload()
    test_simple_text_parser_rejects_invalid_pdf_header()
    logger.info("Parser Service 单元测试通过")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s [%(name)s] %(message)s")
    main()

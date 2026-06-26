"""
Chat Visible Progress Tests

负责：
1. 验证后端只向普通聊天流输出用户可见进度字段。
2. 验证内部 trace 会被映射、去重并清洗。
"""

from __future__ import annotations

import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE_DIR))

from app.services.chat_service import ChatService  # noqa: E402


def _service() -> ChatService:
    return object.__new__(ChatService)


def test_progress_event_from_trace_hides_internal_fields() -> None:
    """trace item 中的实现、耗时和策略字段不应进入用户可见 progress 事件。"""

    service = _service()
    event = service._progress_event_from_trace(  # type: ignore[attr-defined]
        {
            "sequence": 7,
            "step": "数据检索规划",
            "implementation": "planner",
            "status": "success",
            "elapsed_ms": 3307,
            "details": {"answer_policy": "STRICT_KB", "project_metadata": True},
            "display_text": "选择：语义检索 + 关键词检索\n跳过：project_metadata、页级检索、图谱检索",
        }
    )

    assert event == {
        "visible": True,
        "stage": "planning",
        "title": "正在规划资料检索方式",
        "status": "success",
        "detail": "已确定资料检索路径",
        "sequence": 7,
    }
    assert "elapsed_ms" not in event
    assert "implementation" not in event
    assert "details" not in event
    assert "STRICT_KB" not in event["detail"]


def test_visible_progress_events_dedupe_and_complete_answering() -> None:
    """多个内部检索节点应合并为一条检索进度，完成态补齐回答阶段。"""

    service = _service()
    events = service._build_visible_progress_events(  # type: ignore[attr-defined]
        [
            {"sequence": 1, "step": "用户意图识别", "status": "success"},
            {"sequence": 2, "step": "数据检索规划", "status": "success"},
            {"sequence": 3, "step": "检索执行", "status": "running"},
            {"sequence": 3, "step": "检索执行", "status": "success", "display_text": "Milvus 命中 10 条"},
            {"sequence": 4, "step": "证据判断", "status": "success"},
        ],
        completed=True,
    )

    assert [event["stage"] for event in events] == [
        "understanding",
        "planning",
        "retrieving",
        "filtering",
        "answering",
    ]
    assert [event["status"] for event in events] == ["success", "success", "success", "success", "success"]
    assert events[2]["title"] == "正在检索相关资料"
    assert events[2]["detail"] == "已完成相关资料查找"


def test_sanitize_stream_result_strips_raw_trace_payload() -> None:
    """流式 done 事件不能把 raw 调试信息和内部 trace 发给普通用户界面。"""

    service = _service()
    result = {
        "answer": "ok",
        "used_retrievers": ["milvus", "graphrag"],
        "intent_type": "project_qa",
        "answer_policy": "STRICT_KB",
        "evidence_status": "EMPTY",
        "agent_trace": [{"sequence": 1, "step": "回答生成", "status": "success", "elapsed_ms": 12}],
        "trace_steps": [{"sequence": 1, "step": "回答生成", "status": "success", "elapsed_ms": 12}],
        "raw": {"message_id": 42, "run_id": "internal", "project_metadata": {"debug": True}},
    }

    safe_result = service._sanitize_stream_result(result)  # type: ignore[attr-defined]

    assert safe_result["agent_trace"] == []
    assert safe_result["trace_steps"] == []
    assert safe_result["trace"] == []
    assert safe_result["raw"] == {"message_id": 42}
    assert safe_result["used_retrievers"] == []
    assert "intent_type" not in safe_result
    assert "answer_policy" not in safe_result
    assert "evidence_status" not in safe_result
    assert [event["stage"] for event in safe_result["progress_events"]] == [
        "understanding",
        "planning",
        "retrieving",
        "filtering",
        "answering",
    ]
    assert safe_result["progress_events"][-1] == {
        "visible": True,
        "stage": "answering",
        "title": "正在整理回答内容",
        "status": "success",
        "detail": "已完成回答整理",
        "sequence": 1,
    }

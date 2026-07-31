"""
Chat Visible Progress Tests

负责：
1. 验证后端只向普通聊天流输出用户可见进度字段。
2. 验证内部 trace 会被映射、去重并清洗。
"""

from __future__ import annotations

import json
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


def test_sanitize_stream_result_keeps_plan_metadata_and_removes_internal_multi_intent_copy() -> None:
    """后端返回的自定义进度事件必须保留计划元信息，并过滤内部子问题计数文案。"""

    service = _service()
    result = {
        "answer": "ok",
        "used_retrievers": [],
        "agent_trace": [],
        "trace_steps": [],
        "progress_events": [
            {
                "visible": True,
                "event_type": "turn.planned",
                "turn_id": 18,
                "plan_version": 1,
                "stage": "planning",
                "title": "已建立执行计划",
                "status": "success",
                "detail": "将按本轮计划执行",
                "sequence": 1,
                "execution_status": "completed",
                "answerability_status": "unavailable",
            },
            {
                "visible": True,
                "event_type": "intent.completed",
                "turn_id": 18,
                "plan_version": 1,
                "intent_id": "intent-1",
                "intent_name": "装机功率统计",
                "stage": "filtering",
                "title": "装机功率统计",
                "status": "success",
                "detail": "完成 2/2 个子问题",
                "sequence": 2,
                "execution_status": "completed",
                "answerability_status": "insufficient_evidence",
            },
        ],
        "raw": {"message_id": 42},
    }

    safe_result = service._sanitize_stream_result(result)  # type: ignore[attr-defined]

    assert safe_result["progress_events"][0]["turn_id"] == 18
    assert safe_result["progress_events"][0]["plan_version"] == 1
    assert safe_result["progress_events"][1]["intent_id"] == "intent-1"
    assert safe_result["progress_events"][1]["answerability_status"] == "insufficient_evidence"
    assert "完成 2/2 个子问题" not in json.dumps(safe_result["progress_events"], ensure_ascii=False)
    assert "资料不足，未获得明确答案" in json.dumps(safe_result["progress_events"], ensure_ascii=False)

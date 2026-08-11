"""问答 Trace 公共服务行为测试。"""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

BASE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE_DIR))

from app.models.base import Base  # noqa: E402
from app.models.question_answer_trace import QuestionAnswerTraceEvent  # noqa: E402
from app.models.user import User  # noqa: E402
from app.services.question_answer_trace_service import QuestionAnswerTraceService  # noqa: E402
from app.services.question_answer_trace_publisher import QuestionAnswerTracePublisher  # noqa: E402
from app.services.chat_service import ChatService  # noqa: E402


def make_db() -> Session:
    """创建使用真实 Repository 的内存数据库。"""

    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(bind=engine)
    return Session(engine)


def test_question_entry_event_creates_queryable_root_trace() -> None:
    """问题进入事件被消费后，应能通过 trace_id 查询根 Trace。"""

    db = make_db()
    service = QuestionAnswerTraceService(db)

    event = service.build_event(
        trace_id="trace-001",
        event_id="event-001",
        node_id="question-entry",
        business_stage="question_entry",
        event_type="trace.started",
        sequence=1,
        producer="chat_service",
        payload={"question": "酸浸温度是多少？", "chat_type": "project_chat"},
    )
    service.consume(event)

    trace = service.get_trace("trace-001")

    assert trace is not None
    assert trace["trace_id"] == "trace-001"
    assert trace["status"] == "running"
    assert trace["completeness_status"] == "partial"
    assert trace["question"] == "酸浸温度是多少？"
    assert trace["event_count"] == 1


def test_duplicate_event_is_idempotent() -> None:
    """至少一次投递产生重复事件时，Trace 只计入一次。"""

    db = make_db()
    service = QuestionAnswerTraceService(db)
    event = service.build_event(
        trace_id="trace-duplicate",
        event_id="same-event",
        node_id="question-entry",
        business_stage="question_entry",
        event_type="trace.started",
        sequence=1,
        producer="chat_service",
        payload={"question": "重复投递会怎样？"},
    )

    first_result = service.consume(event)
    second_result = service.consume(event)
    trace = service.get_trace("trace-duplicate")

    assert first_result is True
    assert second_result is False
    assert trace is not None
    assert trace["event_count"] == 1


class FailingQueue:
    """模拟不可用的外部消息队列边界。"""

    def enqueue(self, *_args: object, **_kwargs: object) -> None:
        raise ConnectionError("queue unavailable")


def test_trace_publish_failure_does_not_escape_to_question_answer_flow() -> None:
    """Trace 队列异常时，发布失败不得中断问答调用方。"""

    publisher = QuestionAnswerTracePublisher(queue=FailingQueue())

    published = publisher.publish({"trace_id": "trace-fail-open", "event_id": "event-1"})

    assert published is False


def test_out_of_order_terminal_event_stays_incomplete_until_sequence_is_contiguous() -> None:
    """终止事件先到时，只有补齐全部序号后才能标记完整。"""

    db = make_db()
    service = QuestionAnswerTraceService(db)

    def consume(sequence: int, event_type: str) -> None:
        service.consume(
            service.build_event(
                trace_id="trace-out-of-order",
                event_id=f"event-{sequence}",
                node_id=f"node-{sequence}",
                business_stage="result_return" if sequence == 3 else "question_understanding",
                event_type=event_type,
                sequence=sequence,
                producer="test",
                payload={},
            )
        )

    consume(3, "trace.completed")
    assert service.get_trace("trace-out-of-order")["completeness_status"] == "incomplete"

    consume(1, "trace.started")
    assert service.get_trace("trace-out-of-order")["completeness_status"] == "incomplete"

    consume(2, "node.completed")
    trace = service.get_trace("trace-out-of-order")
    assert trace is not None
    assert trace["status"] == "success"
    assert trace["completeness_status"] == "complete"


def test_tampered_event_payload_is_rejected() -> None:
    """事件载荷与校验和不一致时不得进入 Trace。"""

    db = make_db()
    service = QuestionAnswerTraceService(db)
    event = service.build_event(
        trace_id="trace-checksum",
        event_id="event-checksum",
        node_id="question-entry",
        business_stage="question_entry",
        event_type="trace.started",
        sequence=1,
        producer="chat_service",
        payload={"question": "原始问题"},
    )
    event["payload"]["question"] = "被篡改的问题"

    with pytest.raises(ValueError, match="checksum"):
        service.consume(event)

    assert service.get_trace("trace-checksum") is None


def test_trace_keeps_question_identity_and_returns_events_in_sequence_order() -> None:
    """根 Trace 应关联问答身份，乱序事件应按执行序号查询。"""

    db = make_db()
    service = QuestionAnswerTraceService(db)
    for sequence in (2, 1):
        service.consume(
            service.build_event(
                trace_id="trace-linked",
                event_id=f"event-{sequence}",
                node_id=f"node-{sequence}",
                business_stage="question_understanding" if sequence == 2 else "question_entry",
                event_type="node.completed" if sequence == 2 else "trace.started",
                sequence=sequence,
                producer="chat_service",
                payload={
                    "question": "关联哪一轮问答？",
                    "user_id": 7,
                    "session_id": 11,
                    "user_message_id": 19,
                    "project_id": 23,
                },
            )
        )

    trace = service.get_trace("trace-linked")
    events = service.list_events("trace-linked")

    assert trace is not None
    assert trace["user_id"] == 7
    assert trace["session_id"] == 11
    assert trace["user_message_id"] == 19
    assert trace["project_id"] == 23
    assert [event["sequence"] for event in events] == [1, 2]


def test_execution_steps_become_stage_events_without_losing_observable_details() -> None:
    """真实执行节点应映射到业务阶段，并完整保留可观测字段。"""

    db = make_db()
    service = QuestionAnswerTraceService(db)
    events = service.build_execution_events(
        trace_id="trace-execution",
        agent_trace=[
            {
                "step": "session_memory",
                "sequence": 1,
                "status": "success",
                "elapsed_ms": 14,
                "implementation": "ChatMemoryService",
                "input_summary": {"original_question": "它的温度呢？"},
                "output_summary": {"effective_question": "酸浸工序的温度呢？"},
                "details": {"memory_mode": "rewrite_single", "referenced_context_ids": ["topic::acid"]},
            },
            {
                "step": "retrieval_planner",
                "sequence": 2,
                "status": "success",
                "elapsed_ms": 8,
                "implementation": "RetrievalPlannerService",
                "input_summary": {"query": "酸浸工序的温度呢？"},
                "output_summary": {"selected_retrievers": ["milvus"]},
                "details": {"top_k": 20, "fusion_algorithm": "rrf", "score_threshold": 0.42},
            },
        ],
    )

    assert [event["business_stage"] for event in events] == ["question_understanding", "retrieval_planning"]
    assert events[0]["payload"]["output"]["effective_question"] == "酸浸工序的温度呢？"
    assert events[0]["payload"]["details"]["referenced_context_ids"] == ["topic::acid"]
    assert events[1]["payload"]["effective_config"]["top_k"] == 20
    assert events[1]["payload"]["effective_config"]["fusion_algorithm"] == "rrf"


def test_chinese_execution_nodes_map_to_stable_business_stages() -> None:
    """真实中文节点名应映射到稳定业务阶段，而不是全部落入默认阶段。"""

    service = QuestionAnswerTraceService(make_db())

    events = service.build_execution_events(
        trace_id="trace-chinese-stages",
        agent_trace=[
            {"step": "检索召回与数据组装"},
            {"step": "资料证据有效性判断"},
            {"step": "回答生成"},
            {"step": "敏感信息过滤"},
        ],
    )

    assert [event["business_stage"] for event in events] == [
        "multi_route_recall",
        "evidence_judgment",
        "answer_generation",
        "sensitive_filtering",
    ]


def test_event_payload_is_json_safe_and_keeps_execution_relationships() -> None:
    """采集对象类型不得影响问答，节点关系应原样进入事件。"""

    service = QuestionAnswerTraceService(make_db())
    events = service.build_execution_events(
        trace_id="trace-json-safe",
        agent_trace=[
            {
                "step": "retrieval",
                "node_id": "retrieval-2",
                "parent_node_id": "intent-1",
                "depends_on": ["planner-1"],
                "parallel_group_id": "recall-group-1",
                "details": {
                    "observed_at": datetime(2026, 8, 6, tzinfo=UTC),
                    "retrievers": {"vector", "keyword"},
                },
            }
        ],
    )

    event = events[0]
    json_payload = event["payload"]
    assert event["node_id"] == "retrieval-2"
    assert event["parent_node_id"] == "intent-1"
    assert json_payload["depends_on"] == ["planner-1"]
    assert json_payload["parallel_group_id"] == "recall-group-1"
    assert json_payload["details"]["observed_at"] == "2026-08-06T00:00:00+00:00"
    assert sorted(json_payload["details"]["retrievers"]) == ["keyword", "vector"]


def test_effective_config_is_extracted_recursively_with_its_source() -> None:
    """嵌套计划中的生效参数及配置来源应在节点摘要中一并保留。"""

    service = QuestionAnswerTraceService(make_db())
    event = service.build_execution_events(
        trace_id="trace-nested-config",
        agent_trace=[
            {
                "step": "数据检索规划",
                "details": {
                    "retrieval_plan": {
                        "vector": {"top_k": 20, "score_threshold": 0.42},
                        "fusion": {"algorithm": "rrf", "weights": {"vector": 0.7}},
                        "source": "project_policy",
                    }
                },
            }
        ],
    )[0]

    config = event["payload"]["effective_config"]["retrieval_plan"]
    assert config["vector"] == {"top_k": 20, "score_threshold": 0.42}
    assert config["fusion"]["algorithm"] == "rrf"
    assert config["source"] == "project_policy"


def test_combined_nodes_emit_explicit_rerank_and_sensitive_filter_stages() -> None:
    """实现中合并执行的动作仍应拆为可单独查看的稳定业务阶段。"""

    service = QuestionAnswerTraceService(make_db())
    events = service.build_execution_events(
        trace_id="trace-expanded-stages",
        runtime_observability={
            "retrieval_before_rerank_candidates": [{"chunk_id": 1, "score": 0.7}],
            "rerank_after_candidates": [{"chunk_id": 1, "score": 0.9}],
            "rerank_details": [{"chunk_id": 1, "rank_before": 2, "rank_after": 1}],
            "sensitive_filter": {
                "before_content": "报价 100 万元",
                "after_content": "报价 [已隐藏]",
                "action": "redact",
            },
        },
        agent_trace=[
            {
                "step": "检索召回与数据组装",
                "details": {},
            },
            {
                "step": "回答生成",
                "details": {},
            },
        ],
    )

    assert [event["business_stage"] for event in events] == [
        "multi_route_recall",
        "reranking",
        "answer_generation",
        "sensitive_filtering",
    ]
    assert events[1]["payload"]["input"] == [{"chunk_id": 1, "score": 0.7}]
    assert events[1]["payload"]["output"] == [{"chunk_id": 1, "score": 0.9}]
    assert events[3]["payload"]["action"] == "redact"
    assert [event["sequence"] for event in events] == [2, 3, 4, 5]


def test_multi_intent_trace_emits_intent_and_sub_question_hierarchy() -> None:
    """多意图执行应生成意图、子问题和真实节点三级结构及依赖关系。"""

    service = QuestionAnswerTraceService(make_db())
    events = service.build_execution_events(
        trace_id="trace-multi-intent",
        runtime_observability={
            "intent_results": [
                {
                    "id": "intent-1",
                    "name": "温度",
                    "order": 1,
                    "status": "completed",
                    "sub_question_outcomes": [
                        {"id": "sub-1", "order": 1, "question": "温度是多少？", "status": "completed"},
                        {
                            "id": "sub-2",
                            "order": 2,
                            "question": "为何使用该温度？",
                            "status": "completed",
                            "depends_on": ["sub-1"],
                        },
                    ],
                }
            ]
        },
        agent_trace=[
            {
                "step": "资料证据有效性判断",
                "intent_id": "intent-1",
                "sub_question_id": "sub-2",
                "status": "success",
            }
        ],
    )

    intent_event, sub_1, sub_2, node_event = events
    assert intent_event["node_id"] == "intent:intent-1"
    assert intent_event["parent_node_id"] == "question-entry"
    assert sub_1["parent_node_id"] == "intent:intent-1"
    assert sub_2["payload"]["depends_on"] == ["sub-question:sub-1"]
    assert node_event["parent_node_id"] == "sub-question:sub-2"
    assert node_event["payload"]["intent_id"] == "intent-1"
    assert [event["sequence"] for event in events] == [2, 3, 4, 5]


def test_stage_coverage_marks_unexecuted_direct_answer_stages_as_skipped() -> None:
    """直接回答等短路路径也应明确说明哪些稳定阶段未执行。"""

    service = QuestionAnswerTraceService(make_db())
    execution_events = service.build_execution_events(
        trace_id="trace-direct-answer",
        agent_trace=[{"step": "快速意图门控"}, {"step": "回答生成"}],
    )

    coverage_events = service.build_stage_coverage_events(
        trace_id="trace-direct-answer",
        execution_events=execution_events,
    )

    skipped = {event["business_stage"]: event for event in coverage_events}
    assert skipped["retrieval_planning"]["event_type"] == "stage.skipped"
    assert skipped["multi_route_recall"]["payload"]["reason"] == "execution_path_did_not_enter_stage"
    assert skipped["reranking"]["payload"]["status"] == "skipped"
    assert skipped["evidence_judgment"]["payload"]["status"] == "skipped"
    assert skipped["sensitive_filtering"]["payload"]["status"] == "skipped"
    assert [event["sequence"] for event in coverage_events] == list(
        range(len(execution_events) + 2, len(execution_events) + 2 + len(coverage_events))
    )


def test_debugger_returns_stage_summary_pagination_and_historical_credential_redaction() -> None:
    """Debugger 查询应提供阶段摘要、分页事件，并防御历史脏载荷。"""

    db = make_db()
    service = QuestionAnswerTraceService(db)
    for sequence, event_type in ((1, "trace.started"), (2, "trace.completed")):
        event = service.build_event(
            trace_id="trace-debugger-query",
            event_id=f"debugger-{sequence}",
            node_id="question-entry" if sequence == 1 else "result-return",
            business_stage="question_entry" if sequence == 1 else "result_return",
            event_type=event_type,
            sequence=sequence,
            producer="test",
            payload={"authorization": "Bearer secret", "elapsed_ms": 12},
        )
        service.consume(event)

    result = service.get_debugger("trace-debugger-query", offset=1, limit=1)

    assert result is not None
    assert result["trace"]["completeness_status"] == "complete"
    assert result["events_total"] == 2
    assert len(result["events"]) == 1
    assert result["events"][0]["payload"] is None
    detail = service.get_debugger_event("trace-debugger-query", "debugger-2")
    assert detail is not None
    assert "authorization" not in detail["payload"]
    assert result["stages"][0]["event_count"] == 1


def test_trace_aggregate_can_be_rebuilt_idempotently_and_cleaned_without_chat_data() -> None:
    """事件重放不重复累计，清理只删除 Trace 自身。"""

    db = make_db()
    service = QuestionAnswerTraceService(db)
    for sequence, event_type in ((1, "trace.started"), (2, "trace.completed")):
        service.consume(
            service.build_event(
                trace_id="trace-rebuild",
                event_id=f"rebuild-{sequence}",
                node_id="node",
                business_stage="question_entry",
                event_type=event_type,
                sequence=sequence,
                producer="test",
                payload={"question": "重建测试"},
            )
        )

    rebuilt = service.rebuild_trace("trace-rebuild")
    rebuilt_again = service.rebuild_trace("trace-rebuild")

    assert rebuilt is not None
    assert rebuilt_again is not None
    assert rebuilt_again["event_count"] == 2
    assert rebuilt_again["completeness_status"] == "complete"
    assert service.delete_trace("trace-rebuild") == 2
    assert service.get_trace("trace-rebuild") is None


def test_operational_metrics_exposes_incomplete_trace_alert() -> None:
    """运维查询应能识别终止事件缺失的 Trace。"""

    db = make_db()
    service = QuestionAnswerTraceService(db)
    service.consume(
        service.build_event(
            trace_id="trace-metric-incomplete",
            event_id="metric-1",
            node_id="question-entry",
            business_stage="question_entry",
            event_type="trace.completed",
            sequence=3,
            producer="test",
            payload={},
        )
    )

    metrics = service.operational_metrics()

    assert metrics["incomplete_count"] == 1
    assert metrics["alerts"][0]["code"] == "qa_trace_incomplete"


def test_large_payload_is_compressed_at_rest_and_restored_on_demand() -> None:
    """大载荷不得拖慢摘要查询，节点详情仍应无损返回完整业务内容。"""

    db = make_db()
    service = QuestionAnswerTraceService(db)
    large_prompt = "工艺参数与证据上下文" * 20_000
    event = service.build_event(
        trace_id="trace-large-payload",
        event_id="large-event",
        node_id="answer-generation",
        business_stage="answer_generation",
        event_type="node.completed",
        sequence=1,
        producer="test",
        payload={"prompt": large_prompt},
    )

    service.consume(event)

    stored = db.scalar(select(QuestionAnswerTraceEvent).where(QuestionAnswerTraceEvent.event_id == "large-event"))
    assert stored is not None
    assert stored.payload_ref == "inline:gzip+base64"
    assert large_prompt not in stored.payload_json
    summary = service.get_debugger("trace-large-payload")
    assert summary is not None
    assert summary["events"][0]["payload"] is None
    detail = service.get_debugger_event("trace-large-payload", "large-event")
    assert detail is not None
    assert detail["payload"]["prompt"] == large_prompt


def test_duplicate_event_does_not_rollback_outer_transaction() -> None:
    """幂等冲突只能回滚事件 savepoint，不得撤销调用方的其他业务写入。"""

    db = make_db()
    service = QuestionAnswerTraceService(db)
    event = service.build_event(
        trace_id="trace-savepoint",
        event_id="same-event",
        node_id="question-entry",
        business_stage="question_entry",
        event_type="trace.started",
        sequence=1,
        producer="test",
        payload={},
    )
    assert service.consume(event) is True
    db.add(User(username="outer-change", password_hash="x", real_name="Outer Change"))

    assert service.consume(event) is False
    db.commit()

    assert db.query(User).filter(User.username == "outer-change").one_or_none() is not None


def test_debugger_summary_does_not_decode_payloads() -> None:
    """概览只能读取元数据和聚合，不得触发大载荷解码。"""

    db = make_db()
    service = QuestionAnswerTraceService(db)
    event = service.build_event(
        trace_id="trace-summary-only",
        event_id="summary-event",
        node_id="answer-generation",
        business_stage="answer_generation",
        event_type="node.completed",
        sequence=1,
        producer="test",
        payload={"prompt": "large" * 20_000},
    )
    service.consume(event)
    service._decode_payload = lambda _event: (_ for _ in ()).throw(AssertionError("payload decoded"))  # type: ignore[method-assign]

    result = service.get_debugger("trace-summary-only")

    assert result is not None
    assert result["events"][0]["payload"] is None
    assert result["stages"][0]["event_count"] == 1


def test_legacy_schema_event_is_upgraded_and_future_schema_is_rejected() -> None:
    """历史 v0 信封应可读取，未知未来版本必须明确拒绝。"""

    db = make_db()
    service = QuestionAnswerTraceService(db)
    legacy = service.build_event(
        trace_id="trace-schema",
        event_id="legacy-event",
        node_id="question-entry",
        business_stage="question_entry",
        event_type="trace.started",
        sequence=1,
        producer="legacy",
        payload={"question": "历史问题"},
    )
    legacy.pop("schema_version")
    legacy.pop("parent_node_id")
    assert service.consume(legacy) is True
    assert service.get_debugger_event("trace-schema", "legacy-event")["payload"]["question"] == "历史问题"

    future = {**legacy, "event_id": "future-event", "schema_version": 99}
    with pytest.raises(ValueError, match="unsupported.*schema version"):
        service.consume(future)


def test_completed_node_is_published_immediately(monkeypatch: pytest.MonkeyPatch) -> None:
    """真实节点完成时应立即投递，而不是等待整轮问答结束后批量补录。"""

    published: list[dict[str, Any]] = []

    class CapturingPublisher:
        def publish(self, envelope: dict[str, Any]) -> bool:
            published.append(envelope)
            return True

    monkeypatch.setattr("app.services.chat_service.QuestionAnswerTracePublisher", CapturingPublisher)
    observer, observed_events = ChatService(make_db())._question_answer_trace_observer("trace-live-node")

    observer(
        {
            "sequence": 1,
            "step": "检索召回与数据组装",
            "implementation": "retrieval",
            "status": "success",
            "elapsed_ms": 12,
            "details": {"candidate_count": 3},
        }
    )

    assert len(published) == 1
    assert observed_events == published
    assert published[0]["business_stage"] == "multi_route_recall"
    assert published[0]["sequence"] == 2

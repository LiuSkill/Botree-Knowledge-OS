"""问答 Trace 事件构建、消费与查询服务。"""

from __future__ import annotations

import base64
import gzip
import hashlib
import json
import uuid
from dataclasses import asdict, is_dataclass
from datetime import UTC, date, datetime
from enum import Enum
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.models.question_answer_trace import QuestionAnswerTrace, QuestionAnswerTraceEvent
from app.repositories.question_answer_trace_repository import QuestionAnswerTraceRepository


class QuestionAnswerTraceService:
    """提供问答 Trace 的公开事件消费与查询接口。"""

    LARGE_PAYLOAD_BYTES = 64 * 1024
    INLINE_GZIP_PAYLOAD_REF = "inline:gzip+base64"
    CURRENT_SCHEMA_VERSION = 1
    SUPPORTED_SCHEMA_VERSIONS = frozenset({0, 1})

    def __init__(self, db: Session) -> None:
        self.db = db
        self.repository = QuestionAnswerTraceRepository(db)

    def build_event(
        self,
        *,
        trace_id: str,
        event_id: str,
        node_id: str,
        business_stage: str,
        event_type: str,
        sequence: int,
        producer: str,
        payload: dict[str, Any],
        parent_node_id: str | None = None,
        payload_ref: str | None = None,
    ) -> dict[str, Any]:
        """构建版本化事件信封。"""

        occurred_at = datetime.now(UTC).isoformat()
        clean_payload = self._json_safe(self._without_credentials(payload))
        checksum_source = json.dumps(clean_payload, ensure_ascii=False, sort_keys=True)
        return {
            "schema_version": 1,
            "event_id": event_id,
            "trace_id": trace_id,
            "node_id": node_id,
            "parent_node_id": parent_node_id,
            "business_stage": business_stage,
            "event_type": event_type,
            "sequence": sequence,
            "occurred_at": occurred_at,
            "producer": producer,
            "payload": clean_payload,
            "payload_ref": payload_ref,
            "checksum": hashlib.sha256(checksum_source.encode("utf-8")).hexdigest(),
        }

    def build_execution_events(
        self,
        *,
        trace_id: str,
        agent_trace: list[dict[str, Any]],
        runtime_observability: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """把真实执行节点转换为统一的阶段事件。"""

        events: list[dict[str, Any]] = []
        runtime = runtime_observability or {}
        for intent in runtime.get("intent_results", []):
            intent_id = str(intent.get("id") or "")
            if not intent_id:
                continue
            intent_status = str(intent.get("status") or "completed")
            events.append(
                self.build_event(
                    trace_id=trace_id,
                    event_id=uuid.uuid4().hex,
                    node_id=f"intent:{intent_id}",
                    parent_node_id="question-entry",
                    business_stage="question_understanding",
                    event_type=f"intent.{intent_status}",
                    sequence=len(events) + 2,
                    producer="multi_intent_orchestration",
                    payload={key: value for key, value in intent.items() if key != "sub_question_outcomes"},
                )
            )
            for sub_question in intent.get("sub_question_outcomes", []):
                sub_question_id = str(sub_question.get("id") or "")
                if not sub_question_id:
                    continue
                depends_on = [f"sub-question:{item}" for item in sub_question.get("depends_on", [])]
                events.append(
                    self.build_event(
                        trace_id=trace_id,
                        event_id=uuid.uuid4().hex,
                        node_id=f"sub-question:{sub_question_id}",
                        parent_node_id=f"intent:{intent_id}",
                        business_stage="question_understanding",
                        event_type=f"sub_question.{sub_question.get('status') or 'completed'}",
                        sequence=len(events) + 2,
                        producer="multi_intent_orchestration",
                        payload={**sub_question, "depends_on": depends_on},
                    )
                )
        for index, step in enumerate(agent_trace, start=1):
            step_name = str(step.get("step") or f"node-{index}")
            status = str(step.get("status") or "success")
            details = dict(step.get("details") or {})
            node_id = str(step.get("node_id") or f"{step_name}:{index}")
            intent_id = step.get("intent_id")
            sub_question_id = step.get("sub_question_id")
            inferred_parent_id = (
                f"sub-question:{sub_question_id}"
                if sub_question_id
                else (f"intent:{intent_id}" if intent_id else "question-entry")
            )
            payload = {
                "step": step_name,
                "status": status,
                "elapsed_ms": int(step.get("elapsed_ms") or 0),
                "implementation": step.get("implementation"),
                "intent": step.get("intent"),
                "sub_query_index": step.get("sub_query_index"),
                "sub_query_total": step.get("sub_query_total"),
                "input": dict(step.get("input_summary") or {}),
                "output": dict(step.get("output_summary") or {}),
                "details": details,
                "effective_config": self._effective_config(details),
                "depends_on": list(step.get("depends_on") or []),
                "parallel_group_id": step.get("parallel_group_id"),
                "intent_id": intent_id,
                "sub_question_id": sub_question_id,
            }
            events.append(
                self.build_event(
                    trace_id=trace_id,
                    event_id=uuid.uuid4().hex,
                    node_id=node_id,
                    parent_node_id=str(step.get("parent_node_id") or inferred_parent_id),
                    business_stage=self._business_stage(step_name),
                    event_type=f"node.{status}",
                    sequence=len(events) + 2,
                    producer="retrieval_graph",
                    payload=payload,
                )
            )
            before_rerank = details.get("retrieval_before_rerank_candidates", runtime.get("retrieval_before_rerank_candidates"))
            after_rerank = details.get("rerank_after_candidates", runtime.get("rerank_after_candidates"))
            if self._business_stage(step_name) == "multi_route_recall" and (
                before_rerank is not None or after_rerank is not None
            ):
                events.append(
                    self.build_event(
                        trace_id=trace_id,
                        event_id=uuid.uuid4().hex,
                        node_id=f"{node_id}:rerank",
                        parent_node_id=node_id,
                        business_stage="reranking",
                        event_type=f"node.{status}",
                        sequence=len(events) + 2,
                        producer="retrieval_graph",
                        payload={
                            "step": "重排",
                            "status": status,
                            "input": before_rerank or [],
                            "output": after_rerank or [],
                            "details": details.get("rerank_details") or runtime.get("rerank_details") or [],
                        },
                    )
                )
            sensitive_filter = details.get("sensitive_filter") or runtime.get("sensitive_filter")
            if self._business_stage(step_name) == "answer_generation" and isinstance(sensitive_filter, dict):
                events.append(
                    self.build_event(
                        trace_id=trace_id,
                        event_id=uuid.uuid4().hex,
                        node_id=f"{node_id}:sensitive-filter",
                        parent_node_id=node_id,
                        business_stage="sensitive_filtering",
                        event_type="node.success",
                        sequence=len(events) + 2,
                        producer="retrieval_graph",
                        payload={"step": "敏感信息过滤", "status": "success", **sensitive_filter},
                    )
                )
        return events

    def build_stage_coverage_events(
        self,
        *,
        trace_id: str,
        execution_events: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """为短路、跳过和降级路径补充稳定阶段的明确状态事件。"""

        stages = (
            "question_understanding",
            "retrieval_planning",
            "multi_route_recall",
            "reranking",
            "evidence_judgment",
            "answer_generation",
            "sensitive_filtering",
        )
        observed = {str(event.get("business_stage")) for event in execution_events}
        events: list[dict[str, Any]] = []
        for stage in stages:
            if stage in observed:
                continue
            events.append(
                self.build_event(
                    trace_id=trace_id,
                    event_id=uuid.uuid4().hex,
                    node_id=f"stage:{stage}",
                    parent_node_id="question-entry",
                    business_stage=stage,
                    event_type="stage.skipped",
                    sequence=len(execution_events) + len(events) + 2,
                    producer="question_answer_trace_service",
                    payload={
                        "status": "skipped",
                        "reason": "execution_path_did_not_enter_stage",
                    },
                )
            )
        return events

    def consume(self, envelope: dict[str, Any]) -> bool:
        """幂等消费事件并更新 Trace 聚合。"""

        envelope = self._normalize_envelope(envelope)
        payload = dict(envelope.get("payload") or {})
        checksum_source = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        actual_checksum = hashlib.sha256(checksum_source.encode("utf-8")).hexdigest()
        if actual_checksum != str(envelope.get("checksum") or ""):
            raise ValueError("question answer trace event checksum mismatch")
        payload_json, payload_ref = self._encode_payload(payload, envelope.get("payload_ref"))
        event = QuestionAnswerTraceEvent(
            schema_version=int(envelope["schema_version"]),
            event_id=str(envelope["event_id"]),
            trace_id=str(envelope["trace_id"]),
            node_id=str(envelope["node_id"]),
            parent_node_id=envelope.get("parent_node_id"),
            business_stage=str(envelope["business_stage"]),
            event_type=str(envelope["event_type"]),
            sequence=int(envelope["sequence"]),
            occurred_at=str(envelope["occurred_at"]),
            producer=str(envelope["producer"]),
            payload_json=payload_json,
            payload_ref=payload_ref,
            checksum=str(envelope["checksum"]),
        )
        if not self.repository.add_event(event):
            return False
        trace_id = str(envelope["trace_id"])
        trace = self.repository.get_trace(trace_id)
        if trace is None:
            trace = self.repository.add_trace(QuestionAnswerTrace(trace_id=trace_id))
        trace.event_count += 1
        trace.last_sequence = max(trace.last_sequence, int(envelope["sequence"]))
        trace.question = trace.question or payload.get("question")
        trace.chat_type = trace.chat_type or payload.get("chat_type")
        for field in ("user_id", "session_id", "user_message_id", "assistant_message_id", "project_id"):
            if getattr(trace, field) is None and payload.get(field) is not None:
                setattr(trace, field, int(payload[field]))
        if envelope["event_type"] == "trace.completed":
            trace.status = "success"
            trace.terminal_sequence = int(envelope["sequence"])
        elif envelope["event_type"] == "trace.failed":
            trace.status = "failed"
            trace.terminal_sequence = int(envelope["sequence"])
        if trace.terminal_sequence is not None:
            expected = list(range(1, trace.terminal_sequence + 1))
            trace.completeness_status = (
                "complete" if self.repository.list_sequences(trace_id) == expected else "incomplete"
            )
        self.db.flush()
        return True

    def get_trace(self, trace_id: str) -> dict[str, Any] | None:
        """返回根 Trace 的稳定查询表示。"""

        trace = self.repository.get_trace(trace_id)
        if trace is None:
            return None
        return {
            "trace_id": trace.trace_id,
            "user_id": trace.user_id,
            "session_id": trace.session_id,
            "user_message_id": trace.user_message_id,
            "assistant_message_id": trace.assistant_message_id,
            "project_id": trace.project_id,
            "status": trace.status,
            "completeness_status": trace.completeness_status,
            "question": trace.question,
            "chat_type": trace.chat_type,
            "event_count": trace.event_count,
            "last_sequence": trace.last_sequence,
        }

    def list_events(
        self,
        trace_id: str,
        *,
        offset: int = 0,
        limit: int | None = None,
        business_stage: str | None = None,
    ) -> list[dict[str, Any]]:
        """按真实序号返回 Trace 事件。"""

        return [
            {
                "schema_version": event.schema_version,
                "event_id": event.event_id,
                "trace_id": event.trace_id,
                "node_id": event.node_id,
                "parent_node_id": event.parent_node_id,
                "business_stage": event.business_stage,
                "event_type": event.event_type,
                "sequence": event.sequence,
                "occurred_at": event.occurred_at,
                "producer": event.producer,
                "payload": self._without_credentials(self._decode_payload(event)),
                "payload_ref": event.payload_ref,
                "checksum": event.checksum,
            }
            for event in self.repository.list_events(
                trace_id,
                offset=offset,
                limit=limit,
                business_stage=business_stage,
            )
        ]

    def get_debugger(
        self,
        trace_id: str,
        *,
        offset: int = 0,
        limit: int = 100,
        include_payload: bool = False,
        business_stage: str | None = None,
    ) -> dict[str, Any] | None:
        """返回 Debugger 概览与按序分页事件；历史数据也执行凭据二次清理。"""

        summary = self.get_trace(trace_id)
        if summary is None:
            return None
        if include_payload:
            events = self.list_events(
                trace_id,
                offset=offset,
                limit=limit,
                business_stage=business_stage,
            )
        else:
            events = [
                {**event, "payload": None, "payload_available": True}
                for event in self.repository.list_event_summaries(
                    trace_id,
                    offset=offset,
                    limit=limit,
                    business_stage=business_stage,
                )
            ]
        return {
            "trace": summary,
            "stages": self.repository.stage_summaries(trace_id),
            "events": events,
            "events_offset": offset,
            "events_limit": limit,
            "events_total": self.repository.count_events(trace_id, business_stage=business_stage),
        }

    def get_debugger_event(self, trace_id: str, event_id: str) -> dict[str, Any] | None:
        """按需返回单节点完整载荷。"""

        event = self.repository.get_event(trace_id, event_id)
        if event is None:
            return None
        payload = self._without_credentials(self._decode_payload(event))
        return {
            "event_id": event.event_id,
            "trace_id": event.trace_id,
            "node_id": event.node_id,
            "parent_node_id": event.parent_node_id,
            "business_stage": event.business_stage,
            "event_type": event.event_type,
            "sequence": event.sequence,
            "occurred_at": event.occurred_at,
            "producer": event.producer,
            "payload": payload,
            "payload_ref": event.payload_ref,
            "checksum": event.checksum,
        }

    def rebuild_trace(self, trace_id: str) -> dict[str, Any] | None:
        """从不可变事件重建聚合，支持运维校正而不重复累计。"""

        events = self.repository.list_events(trace_id)
        if not events:
            return None
        rebuilt = QuestionAnswerTrace(trace_id=trace_id)
        self.repository.replace_trace(trace_id, rebuilt)
        for event in events:
            payload = self._without_credentials(self._decode_payload(event))
            rebuilt.event_count += 1
            rebuilt.last_sequence = max(rebuilt.last_sequence, event.sequence)
            rebuilt.question = rebuilt.question or payload.get("question")
            if event.event_type == "trace.completed":
                rebuilt.status = "success"
                rebuilt.terminal_sequence = event.sequence
            elif event.event_type == "trace.failed":
                rebuilt.status = "failed"
                rebuilt.terminal_sequence = event.sequence
        if rebuilt.terminal_sequence is not None:
            rebuilt.completeness_status = (
                "complete" if self.repository.list_sequences(trace_id) == list(range(1, rebuilt.terminal_sequence + 1)) else "incomplete"
            )
        self.db.flush()
        return self.get_trace(trace_id)

    def delete_trace(self, trace_id: str) -> int | None:
        """显式删除 Trace 数据，返回删除事件数。"""

        if self.repository.get_trace(trace_id) is None:
            return None
        return self.repository.delete_trace(trace_id)

    def operational_metrics(self) -> dict[str, Any]:
        """提供可被监控系统轮询的聚合状态与基础告警信号。"""

        counts = self.repository.aggregate_status_counts()
        incomplete = sum(value for key, value in counts.items() if key.endswith(":incomplete"))
        running = sum(value for key, value in counts.items() if key.startswith("running:"))
        alerts: list[dict[str, Any]] = []
        if incomplete:
            alerts.append({"code": "qa_trace_incomplete", "severity": "warning", "count": incomplete})
        if running:
            alerts.append({"code": "qa_trace_running", "severity": "info", "count": running})
        return {"status_counts": counts, "incomplete_count": incomplete, "running_count": running, "alerts": alerts}

    def _without_credentials(self, value: Any) -> Any:
        """递归移除不应进入 Trace 的认证凭据与密钥。"""

        denied = {"authorization", "cookie", "password", "api_key", "apikey", "access_token", "refresh_token", "secret"}
        if isinstance(value, dict):
            return {
                key: self._without_credentials(item)
                for key, item in value.items()
                if str(key).lower() not in denied
            }
        if isinstance(value, list):
            return [self._without_credentials(item) for item in value]
        return value

    def _encode_payload(self, payload: dict[str, Any], payload_ref: str | None) -> tuple[str, str | None]:
        """大载荷压缩后内联保存，避免事件表被重复业务文本快速膨胀。"""

        serialized = json.dumps(payload, ensure_ascii=False)
        if payload_ref is not None or len(serialized.encode("utf-8")) < self.LARGE_PAYLOAD_BYTES:
            return serialized, payload_ref
        compressed = gzip.compress(serialized.encode("utf-8"))
        return base64.b64encode(compressed).decode("ascii"), self.INLINE_GZIP_PAYLOAD_REF

    def _normalize_envelope(self, envelope: dict[str, Any]) -> dict[str, Any]:
        """升级历史事件信封，并明确拒绝尚不支持的未来版本。"""

        normalized = dict(envelope)
        schema_version = int(normalized.get("schema_version", 0))
        if schema_version not in self.SUPPORTED_SCHEMA_VERSIONS:
            raise ValueError(f"unsupported question answer trace schema version: {schema_version}")
        normalized["schema_version"] = schema_version
        if schema_version == 0:
            normalized.setdefault("parent_node_id", None)
            normalized.setdefault("payload_ref", None)
            normalized.setdefault("producer", "legacy")
            normalized.setdefault("occurred_at", datetime.now(UTC).isoformat())
            if not normalized.get("checksum"):
                checksum_source = json.dumps(dict(normalized.get("payload") or {}), ensure_ascii=False, sort_keys=True)
                normalized["checksum"] = hashlib.sha256(checksum_source.encode("utf-8")).hexdigest()
        return normalized

    def _decode_payload(self, event: QuestionAnswerTraceEvent) -> dict[str, Any]:
        """兼容读取历史明文事件与新写入的压缩事件。"""

        if event.schema_version not in self.SUPPORTED_SCHEMA_VERSIONS:
            raise ValueError(f"unsupported question answer trace schema version: {event.schema_version}")
        if event.payload_ref == self.INLINE_GZIP_PAYLOAD_REF:
            raw = gzip.decompress(base64.b64decode(event.payload_json)).decode("utf-8")
            return dict(json.loads(raw))
        return dict(json.loads(event.payload_json))

    def _json_safe(self, value: Any) -> Any:
        """把可观测运行时对象稳定转换为 JSON，采集失败不得反向影响问答。"""

        if value is None or isinstance(value, (str, int, float, bool)):
            return value
        if isinstance(value, (datetime, date)):
            return value.isoformat()
        if isinstance(value, Enum):
            return self._json_safe(value.value)
        if isinstance(value, Path):
            return str(value)
        if isinstance(value, bytes):
            return value.decode("utf-8", errors="replace")
        if is_dataclass(value) and not isinstance(value, type):
            return self._json_safe(asdict(value))
        if isinstance(value, dict):
            return {str(key): self._json_safe(item) for key, item in value.items()}
        if isinstance(value, (list, tuple, set, frozenset)):
            return [self._json_safe(item) for item in value]
        model_dump = getattr(value, "model_dump", None)
        if callable(model_dump):
            return self._json_safe(model_dump(mode="json"))
        to_dict = getattr(value, "to_dict", None)
        if callable(to_dict):
            return self._json_safe(to_dict())
        return str(value)

    def _business_stage(self, step_name: str) -> str:
        """将实现节点映射到稳定的九阶段业务视图。"""

        normalized = step_name.lower()
        if any(value in normalized for value in ("敏感", "过滤", "sensitive", "filter")):
            return "sensitive_filtering"
        if any(value in normalized for value in ("重排", "rerank")) and not any(
            value in normalized for value in ("召回", "检索召回", "retrieval")
        ):
            return "reranking"
        if any(value in normalized for value in ("意图", "记忆", "任务拆解", "查询画像", "问题理解", "intent", "memory", "decompose", "profile", "understanding")):
            return "question_understanding"
        if any(value in normalized for value in ("策略解析", "检索规划", "查询改写", "planner", "policy_resolution", "query_rewrite")):
            return "retrieval_planning"
        if any(value in normalized for value in ("检索", "召回", "融合", "retrieval", "recall", "fusion")):
            return "multi_route_recall"
        if "重排" in normalized or "rerank" in normalized:
            return "reranking"
        if any(value in normalized for value in ("证据", "答案策略", "evidence", "answer_policy_gate")):
            return "evidence_judgment"
        if "回答" in normalized or "answer" in normalized:
            return "answer_generation"
        if "返回" in normalized or "结果" in normalized or "return" in normalized or "final" in normalized:
            return "result_return"
        return "question_understanding"

    def _effective_config(self, details: dict[str, Any]) -> dict[str, Any]:
        """提取本节点实际生效且影响结果的配置值。"""

        markers = ("top_k", "threshold", "weight", "algorithm", "model", "timeout", "retry", "prompt", "enabled")

        def select(mapping: dict[str, Any]) -> dict[str, Any]:
            selected: dict[str, Any] = {}
            for key, value in mapping.items():
                normalized_key = str(key).lower()
                if any(marker in normalized_key for marker in markers):
                    selected[key] = value
                    continue
                if isinstance(value, dict):
                    nested = select(value)
                    if nested:
                        selected[key] = nested
            if selected:
                for context_key in ("source", "reason", "rule_id", "strategy"):
                    if context_key in mapping:
                        selected.setdefault(context_key, mapping[context_key])
            return selected

        return select(details)

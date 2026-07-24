"""
Chat Memory Service

负责：
1. 管理会话级短期记忆快照
2. 为当前回合生成检索前上下文化结果
3. 在回答结束后按规则收敛 confirmed / pending 上下文
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.chat import ChatMessage, ChatSession
from app.models.system_config import SystemConfig
from app.repositories.chat_repository import ChatRepository
from app.retrieval.schemas import Evidence

logger = logging.getLogger(__name__)

MEMORY_SCHEMA_VERSION = 1
DEFAULT_RAW_WINDOW_ROUNDS = 3
MIN_RAW_WINDOW_ROUNDS = 1
MAX_RAW_WINDOW_ROUNDS = 8
PENDING_TTL_TURNS = 2
CONFIRMED_CONTEXT_CAP = 8
PENDING_CONTEXT_CAP = 4
TOPIC_LABEL_MAX_LEN = 80
SUMMARY_MAX_LEN = 160
CONFIG_ENABLED_KEY = "chat_memory_enabled"
CONFIG_WINDOW_ROUNDS_KEY = "chat_memory_raw_window_rounds"

_FOLLOW_UP_PATTERNS: tuple[str, ...] = (
    "这个",
    "那个",
    "它",
    "其",
    "前者",
    "后者",
    "继续",
    "接着",
    "然后",
    "下一步",
    "第二步",
    "第三步",
    "这一步",
    "那一步",
    "那如果",
    "为什么会这样",
    "怎么处理",
    "怎么做",
)
_GENERAL_DIRECT_ANSWER_TYPES = {"preset", "general_llm", "cancelled"}
_PROMOTABLE_ANSWER_TYPES = {
    "normal_answer",
    "limited_answer",
    "partial_answer",
    "partial_answer_with_llm",
    "conflict_answer",
}
_PENDING_ONLY_ANSWER_TYPES = {"refusal", "ask_general_confirm", "clarify"}


class RecentRound(BaseModel):
    """最近对话轮次。"""

    user_message_id: int | None = None
    assistant_message_id: int | None = None
    user_text: str = ""
    assistant_text: str = ""


class MemoryCitationAnchor(BaseModel):
    """短期记忆引用锚点。"""

    citation_id: int
    source_type: str
    knowledge_base_id: int
    project_id: int | None = None
    document_id: int
    chunk_id: int
    file_name: str
    page_number: int | None = None


class MemoryItemAnchor(BaseModel):
    """记忆项来源锚点。"""

    source_message_id: int | None = None
    source_kind: str
    citation_ids: list[int] = Field(default_factory=list)
    confirmed_at: str | None = None
    updated_at: str | None = None


class MemoryContextItem(BaseModel):
    """结构化记忆项。"""

    id: str
    kind: str
    scope: str = "topic"
    summary: str
    anchor: MemoryItemAnchor
    pending_turn_ttl: int | None = None


class TopicContext(BaseModel):
    """当前话题上下文。"""

    topic_key: str | None = None
    topic_label: str | None = None
    current_objects: list[str] = Field(default_factory=list)
    current_problem_chain_summary: str | None = None
    last_active_user_message_id: int | None = None


class LastTurnSummary(BaseModel):
    """最近一轮受控摘要。"""

    user_intent: str | None = None
    assistant_action: str | None = None
    evidence_status: str | None = None
    problem_chain_summary: str | None = None


class TopicShiftSignals(BaseModel):
    """话题切换痕迹。"""

    topic_signature: str | None = None
    last_shift_at: str | None = None
    last_shift_reason: str | None = None


class SessionMemorySnapshot(BaseModel):
    """会话级短期记忆固定 schema。"""

    schema_version: int = MEMORY_SCHEMA_VERSION
    stable_context: dict[str, Any] = Field(default_factory=dict)
    topic_context: TopicContext = Field(default_factory=TopicContext)
    confirmed_contexts: list[MemoryContextItem] = Field(default_factory=list)
    pending_contexts: list[MemoryContextItem] = Field(default_factory=list)
    user_constraints: dict[str, Any] = Field(default_factory=dict)
    last_turn_summary: LastTurnSummary = Field(default_factory=LastTurnSummary)
    topic_shift_signals: TopicShiftSignals = Field(default_factory=TopicShiftSignals)


class TurnContext(BaseModel):
    """本轮问答上下文。"""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    session_id: int
    raw_recent_rounds: list[RecentRound] = Field(default_factory=list)
    session_memory: SessionMemorySnapshot | None = None
    original_question: str
    effective_question: str
    memory_trigger_mode: str = "skip"
    memory_referenced_context_ids: list[str] = Field(default_factory=list)
    answer_memory_context: dict[str, Any] = Field(default_factory=dict)
    memory_trace: dict[str, Any] = Field(default_factory=dict)


class TurnOutcome(BaseModel):
    """本轮回答收敛结果。"""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    session_id: int
    user_message_id: int
    assistant_message_id: int | None = None
    user_message: str
    answer: str
    answer_type: str
    evidence_status: str
    chat_type: str
    project_id: int | None = None
    citations: list[MemoryCitationAnchor] = Field(default_factory=list)
    evidences: list[Evidence] = Field(default_factory=list)
    trace_steps: list[dict[str, Any]] = Field(default_factory=list)
    raw: dict[str, Any] = Field(default_factory=dict)
    turn_context: TurnContext | None = None


class MemoryFinalizeResult(BaseModel):
    """短期记忆写回结果。"""

    updated: bool
    session_memory: SessionMemorySnapshot
    writeback_status: str
    writeback_reason: str | None = None


class ChatMemoryConfig(BaseModel):
    """短期记忆平台配置。"""

    enabled: bool = True
    raw_window_rounds: int = DEFAULT_RAW_WINDOW_ROUNDS


class ChatMemoryConfigProvider:
    """读取短期记忆平台级配置，并做进程内短 TTL 缓存。"""

    CACHE_TTL_SECONDS = 30.0
    _cache: dict[str, tuple[float, ChatMemoryConfig]] = {}

    def __init__(self, db: Session) -> None:
        self.db = db

    def get(self) -> ChatMemoryConfig:
        cache_key = self._cache_key()
        now = time.monotonic()
        cached = self._cache.get(cache_key)
        if cached is not None and now - cached[0] < self.CACHE_TTL_SECONDS:
            return cached[1]

        rows = list(
            self.db.scalars(
                select(SystemConfig).where(SystemConfig.config_key.in_((CONFIG_ENABLED_KEY, CONFIG_WINDOW_ROUNDS_KEY)))
            ).all()
        )
        row_map = {row.config_key: row.config_value for row in rows}
        config = ChatMemoryConfig(
            enabled=self._parse_bool(row_map.get(CONFIG_ENABLED_KEY), default=True),
            raw_window_rounds=self._clamp_rounds(row_map.get(CONFIG_WINDOW_ROUNDS_KEY)),
        )
        self._cache[cache_key] = (now, config)
        return config

    def _cache_key(self) -> str:
        bind = self.db.get_bind()
        return str(getattr(bind, "url", "memory"))

    def _parse_bool(self, value: str | None, *, default: bool) -> bool:
        if value is None:
            return default
        text = str(value).strip().lower()
        if text in {"1", "true", "yes", "on"}:
            return True
        if text in {"0", "false", "no", "off"}:
            return False
        return default

    def _clamp_rounds(self, value: str | None) -> int:
        if value is None:
            return DEFAULT_RAW_WINDOW_ROUNDS
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            return DEFAULT_RAW_WINDOW_ROUNDS
        return max(MIN_RAW_WINDOW_ROUNDS, min(MAX_RAW_WINDOW_ROUNDS, parsed))


class ChatMemoryService:
    """
    会话级短期记忆服务。

    设计目标：
    - 把上下文化判定、TTL、topic shift 和快照序列化收敛到一个深模块
    - 只向外暴露 prepare_turn_context / finalize_turn_memory 两个接口
    """

    def __init__(self, db: Session) -> None:
        self.db = db
        self.repository = ChatRepository(db)
        self.config_provider = ChatMemoryConfigProvider(db)

    def prepare_turn_context(
        self,
        session: ChatSession,
        user_message: ChatMessage,
        question: str,
    ) -> TurnContext:
        """准备本轮短期记忆上下文；失败时降级为无记忆上下文。"""

        started_at = time.perf_counter()
        try:
            config = self.config_provider.get()
            snapshot = self._load_snapshot(session)
            recent_messages = self.repository.list_recent_round_messages(session.id, config.raw_window_rounds)
            recent_rounds = self._build_recent_rounds(recent_messages, config.raw_window_rounds)
            topic_shift = self._detect_topic_shift(question, snapshot)
            working_snapshot = self._snapshot_after_read_prune(snapshot, topic_shift)
            memory_source = self._memory_source_for_rewrite(working_snapshot, recent_rounds)

            trigger_mode = "skip"
            decision_reason = "disabled" if not config.enabled else "no_memory"
            referenced_ids: list[str] = []
            effective_question = question
            confidence = self._memory_confidence(working_snapshot)

            if config.enabled:
                if topic_shift["strong"]:
                    decision_reason = "topic_shift"
                elif self._is_context_dependent(question):
                    if memory_source is not None:
                        trigger_mode = "rewrite_single"
                        decision_reason = "context_dependent_with_memory"
                        referenced_ids = [memory_source["id"]]
                        effective_question = self._rewrite_question(memory_source["topic_label"], question)
                    else:
                        decision_reason = "context_dependent_low_confidence"
                elif self._is_question_complete(question):
                    decision_reason = "question_complete"
                else:
                    decision_reason = "skip"

            prepare_ms = int((time.perf_counter() - started_at) * 1000)
            return TurnContext(
                session_id=session.id,
                raw_recent_rounds=recent_rounds,
                session_memory=working_snapshot,
                original_question=question,
                effective_question=effective_question,
                memory_trigger_mode=trigger_mode,
                memory_referenced_context_ids=referenced_ids,
                answer_memory_context=self._build_answer_memory_context(working_snapshot, memory_source, effective_question, question),
                memory_trace={
                    "prepare_ms": prepare_ms,
                    "trigger_mode": trigger_mode,
                    "decision_reason": decision_reason,
                    "original_question": question,
                    "effective_question": effective_question,
                    "topic_shift": topic_shift,
                    "memory_confidence": confidence,
                    "referenced_context_ids": referenced_ids,
                },
            )
        except Exception:  # noqa: BLE001
            logger.exception("会话短期记忆准备失败: session_id=%s", getattr(session, "id", None))
            return TurnContext(
                session_id=session.id,
                raw_recent_rounds=[],
                session_memory=None,
                original_question=question,
                effective_question=question,
                memory_trigger_mode="skip",
                answer_memory_context={},
                memory_trace={
                    "prepare_ms": int((time.perf_counter() - started_at) * 1000),
                    "trigger_mode": "skip",
                    "decision_reason": "prepare_failed",
                    "original_question": question,
                    "effective_question": question,
                    "topic_shift": {"strong": False, "reason": "prepare_failed"},
                    "memory_confidence": "none",
                    "referenced_context_ids": [],
                },
            )

    def finalize_turn_memory(self, session: ChatSession, turn_outcome: TurnOutcome) -> MemoryFinalizeResult:
        """在回答完成后按固定 schema 收敛并写回短期记忆。"""

        snapshot = self._load_snapshot(session)
        now_iso = self._iso_now()
        aged_snapshot = self._age_pending(snapshot)
        topic_shift = self._detect_topic_shift(turn_outcome.user_message, aged_snapshot)
        working_snapshot = self._snapshot_after_write_prune(aged_snapshot, topic_shift, now_iso)

        working_snapshot.stable_context = self._build_stable_context(session, turn_outcome)
        working_snapshot.user_constraints = self._merge_user_constraints(
            working_snapshot.user_constraints,
            turn_outcome.user_message,
            turn_outcome.chat_type,
        )

        topic_label = self._derive_topic_label(turn_outcome, working_snapshot)
        topic_key = self._topic_key(topic_label)
        problem_chain_summary = self._clip(f"{turn_outcome.user_message} -> {turn_outcome.answer}", SUMMARY_MAX_LEN)
        working_snapshot.topic_context = TopicContext(
            topic_key=topic_key,
            topic_label=topic_label,
            current_objects=[topic_label] if topic_label else [],
            current_problem_chain_summary=problem_chain_summary,
            last_active_user_message_id=turn_outcome.user_message_id,
        )
        working_snapshot.last_turn_summary = LastTurnSummary(
            user_intent=self._clip(turn_outcome.user_message, SUMMARY_MAX_LEN),
            assistant_action=self._clip(turn_outcome.answer_type, SUMMARY_MAX_LEN),
            evidence_status=self._clip(turn_outcome.evidence_status, SUMMARY_MAX_LEN),
            problem_chain_summary=problem_chain_summary,
        )

        if self._should_promote_confirmed(turn_outcome):
            confirmed_item = self._build_confirmed_item(topic_label, topic_key, turn_outcome, now_iso)
            working_snapshot.pending_contexts = [
                item for item in working_snapshot.pending_contexts if item.id != confirmed_item.id
            ]
            working_snapshot.confirmed_contexts = self._upsert_memory_item(
                working_snapshot.confirmed_contexts,
                confirmed_item,
                cap=CONFIRMED_CONTEXT_CAP,
            )
        elif self._should_store_pending(turn_outcome):
            pending_item = self._build_pending_item(topic_label, topic_key, turn_outcome, now_iso)
            working_snapshot.pending_contexts = self._upsert_memory_item(
                working_snapshot.pending_contexts,
                pending_item,
                cap=PENDING_CONTEXT_CAP,
            )

        if topic_shift["strong"]:
            working_snapshot.topic_shift_signals = TopicShiftSignals(
                topic_signature=topic_key,
                last_shift_at=now_iso,
                last_shift_reason=str(topic_shift["reason"]),
            )

        session.memory_state_json = json.dumps(working_snapshot.model_dump(mode="json"), ensure_ascii=False)
        session.memory_state_version = MEMORY_SCHEMA_VERSION
        session.memory_updated_at = datetime.now(UTC).replace(tzinfo=None)
        session.memory_rebuild_needed = False
        self.repository.update_session(session)
        return MemoryFinalizeResult(
            updated=True,
            session_memory=working_snapshot,
            writeback_status="success",
            writeback_reason=None,
        )

    def _load_snapshot(self, session: ChatSession) -> SessionMemorySnapshot:
        raw = session.memory_state_json
        if not raw:
            return SessionMemorySnapshot()
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("会话短期记忆快照损坏，回退为空快照: session_id=%s", getattr(session, "id", None))
            return SessionMemorySnapshot()
        try:
            return SessionMemorySnapshot.model_validate(data)
        except Exception:  # noqa: BLE001
            logger.warning("会话短期记忆快照结构无效，回退为空快照: session_id=%s", getattr(session, "id", None))
            return SessionMemorySnapshot()

    def _build_recent_rounds(self, messages: list[ChatMessage], round_limit: int) -> list[RecentRound]:
        rounds: list[RecentRound] = []
        current_round: RecentRound | None = None
        for message in messages:
            if message.role == "user":
                current_round = RecentRound(
                    user_message_id=message.id,
                    user_text=message.content,
                )
                rounds.append(current_round)
                continue
            if message.role == "assistant" and current_round is not None and current_round.assistant_message_id is None:
                current_round.assistant_message_id = message.id
                current_round.assistant_text = message.content
        return rounds[-round_limit:]

    def _snapshot_after_read_prune(
        self,
        snapshot: SessionMemorySnapshot,
        topic_shift: dict[str, Any],
    ) -> SessionMemorySnapshot:
        working_snapshot = snapshot.model_copy(deep=True)
        working_snapshot.pending_contexts = [
            item for item in working_snapshot.pending_contexts if int(item.pending_turn_ttl or 0) > 0
        ]
        if topic_shift["strong"]:
            working_snapshot = self._clear_topic_scope(working_snapshot)
        return working_snapshot

    def _snapshot_after_write_prune(
        self,
        snapshot: SessionMemorySnapshot,
        topic_shift: dict[str, Any],
        now_iso: str,
    ) -> SessionMemorySnapshot:
        working_snapshot = snapshot.model_copy(deep=True)
        if topic_shift["strong"]:
            working_snapshot = self._clear_topic_scope(working_snapshot)
            working_snapshot.topic_shift_signals = TopicShiftSignals(
                topic_signature=working_snapshot.topic_context.topic_key,
                last_shift_at=now_iso,
                last_shift_reason=str(topic_shift["reason"]),
            )
        return working_snapshot

    def _age_pending(self, snapshot: SessionMemorySnapshot) -> SessionMemorySnapshot:
        working_snapshot = snapshot.model_copy(deep=True)
        next_pending: list[MemoryContextItem] = []
        for item in working_snapshot.pending_contexts:
            ttl = int(item.pending_turn_ttl or 0) - 1
            if ttl <= 0:
                continue
            next_pending.append(item.model_copy(update={"pending_turn_ttl": ttl}))
        working_snapshot.pending_contexts = next_pending
        return working_snapshot

    def _clear_topic_scope(self, snapshot: SessionMemorySnapshot) -> SessionMemorySnapshot:
        working_snapshot = snapshot.model_copy(deep=True)
        working_snapshot.topic_context = TopicContext()
        working_snapshot.confirmed_contexts = [item for item in working_snapshot.confirmed_contexts if item.scope == "stable"]
        working_snapshot.pending_contexts = [item for item in working_snapshot.pending_contexts if item.scope == "stable"]
        return working_snapshot

    def _memory_source_for_rewrite(
        self,
        snapshot: SessionMemorySnapshot,
        recent_rounds: list[RecentRound],
    ) -> dict[str, Any] | None:
        if snapshot.confirmed_contexts:
            item = snapshot.confirmed_contexts[0]
            return {"id": item.id, "topic_label": item.summary}
        topic_label = str(snapshot.topic_context.topic_label or "").strip()
        if topic_label:
            return {
                "id": f"topic::{snapshot.topic_context.topic_key or self._topic_key(topic_label)}",
                "topic_label": topic_label,
            }
        if snapshot.pending_contexts:
            item = snapshot.pending_contexts[0]
            return {"id": item.id, "topic_label": item.summary}
        if recent_rounds:
            latest_full_round = next(
                (
                    round_item
                    for round_item in reversed(recent_rounds)
                    if round_item.user_text and round_item.assistant_text
                ),
                None,
            )
            if latest_full_round is not None:
                return {
                    "id": f"round::{latest_full_round.user_message_id}",
                    "topic_label": self._clip(latest_full_round.user_text, TOPIC_LABEL_MAX_LEN),
                }
        return None

    def _build_answer_memory_context(
        self,
        snapshot: SessionMemorySnapshot | None,
        memory_source: dict[str, Any] | None,
        effective_question: str,
        original_question: str,
    ) -> dict[str, Any]:
        if snapshot is None:
            return {}
        return {
            "user_constraints": dict(snapshot.user_constraints),
            "current_objects": list(snapshot.topic_context.current_objects),
            "problem_chain_summary": snapshot.last_turn_summary.problem_chain_summary,
            "pronoun_resolution": memory_source["topic_label"] if memory_source and effective_question != original_question else None,
        }

    def _memory_confidence(self, snapshot: SessionMemorySnapshot) -> str:
        if snapshot.confirmed_contexts:
            return "high"
        if snapshot.topic_context.topic_label or snapshot.pending_contexts:
            return "medium"
        return "none"

    def _detect_topic_shift(self, question: str, snapshot: SessionMemorySnapshot) -> dict[str, Any]:
        topic_label = str(snapshot.topic_context.topic_label or "").strip()
        if not topic_label:
            return {"strong": False, "reason": "no_previous_topic"}
        if self._is_context_dependent(question):
            return {"strong": False, "reason": "follow_up_query"}
        if not self._is_question_complete(question):
            return {"strong": False, "reason": "question_not_complete"}
        overlap = self._token_overlap_ratio(question, topic_label)
        if overlap < 0.2:
            return {"strong": True, "reason": "low_topic_overlap", "overlap_ratio": overlap}
        return {"strong": False, "reason": "topic_overlap", "overlap_ratio": overlap}

    def _should_promote_confirmed(self, turn_outcome: TurnOutcome) -> bool:
        return bool(turn_outcome.citations) and turn_outcome.answer_type in _PROMOTABLE_ANSWER_TYPES

    def _should_store_pending(self, turn_outcome: TurnOutcome) -> bool:
        if turn_outcome.answer_type in _GENERAL_DIRECT_ANSWER_TYPES:
            return False
        if not self._clip(turn_outcome.user_message, TOPIC_LABEL_MAX_LEN):
            return False
        if turn_outcome.answer_type in _PENDING_ONLY_ANSWER_TYPES:
            return True
        return not bool(turn_outcome.citations)

    def _build_stable_context(self, session: ChatSession, turn_outcome: TurnOutcome) -> dict[str, Any]:
        return {
            "chat_type": turn_outcome.chat_type,
            "project_id": turn_outcome.project_id,
            "answer_preferences": {},
            "conversation_state": getattr(session, "conversation_state", None),
        }

    def _merge_user_constraints(
        self,
        existing: dict[str, Any],
        question: str,
        chat_type: str,
    ) -> dict[str, Any]:
        merged = dict(existing)
        if "中文" in question:
            merged["language"] = "zh"
        elif "英文" in question or "English" in question:
            merged["language"] = "en"
        if "表格" in question:
            merged["format_preference"] = "table"
        elif "列表" in question:
            merged["format_preference"] = "list"
        if chat_type == "project_chat":
            merged["must_use_project_docs"] = True
            merged["avoid_general_knowledge"] = True
        return merged

    def _derive_topic_label(self, turn_outcome: TurnOutcome, snapshot: SessionMemorySnapshot) -> str:
        raw_question = self._clip(turn_outcome.user_message, TOPIC_LABEL_MAX_LEN)
        if turn_outcome.turn_context and turn_outcome.turn_context.memory_trigger_mode == "rewrite_single":
            previous_label = str(snapshot.topic_context.topic_label or "").strip()
            if previous_label:
                return previous_label
        return raw_question

    def _build_confirmed_item(
        self,
        topic_label: str,
        topic_key: str,
        turn_outcome: TurnOutcome,
        now_iso: str,
    ) -> MemoryContextItem:
        return MemoryContextItem(
            id=f"confirmed::{topic_key}",
            kind="topic_summary",
            scope="topic",
            summary=topic_label,
            anchor=MemoryItemAnchor(
                source_message_id=turn_outcome.user_message_id,
                source_kind="assistant_final_with_citation",
                citation_ids=[item.citation_id for item in turn_outcome.citations],
                confirmed_at=now_iso,
                updated_at=now_iso,
            ),
        )

    def _build_pending_item(
        self,
        topic_label: str,
        topic_key: str,
        turn_outcome: TurnOutcome,
        now_iso: str,
    ) -> MemoryContextItem:
        return MemoryContextItem(
            id=f"pending::{topic_key}",
            kind="topic_summary",
            scope="topic",
            summary=topic_label,
            pending_turn_ttl=PENDING_TTL_TURNS,
            anchor=MemoryItemAnchor(
                source_message_id=turn_outcome.user_message_id,
                source_kind="user_message",
                citation_ids=[],
                confirmed_at=None,
                updated_at=now_iso,
            ),
        )

    def _upsert_memory_item(
        self,
        items: list[MemoryContextItem],
        new_item: MemoryContextItem,
        *,
        cap: int,
    ) -> list[MemoryContextItem]:
        updated: list[MemoryContextItem] = [item for item in items if item.id != new_item.id]
        updated.insert(0, new_item)
        return updated[:cap]

    def _is_context_dependent(self, question: str) -> bool:
        normalized = self._normalize_text(question)
        if any(pattern in question for pattern in _FOLLOW_UP_PATTERNS):
            return True
        return len(normalized) <= 6 and question.endswith("呢")

    def _is_question_complete(self, question: str) -> bool:
        normalized = self._normalize_text(question)
        return not self._is_context_dependent(question) and len(normalized) >= 8

    def _rewrite_question(self, topic_label: str, question: str) -> str:
        clean_topic = self._clip(topic_label, TOPIC_LABEL_MAX_LEN)
        return f"关于{clean_topic}，{question}" if clean_topic else question

    def _topic_key(self, topic_label: str) -> str:
        normalized = self._normalize_text(topic_label) or topic_label
        return hashlib.md5(normalized.encode("utf-8")).hexdigest()[:12]

    def _token_overlap_ratio(self, left: str, right: str) -> float:
        left_tokens = self._text_tokens(left)
        right_tokens = self._text_tokens(right)
        if not left_tokens or not right_tokens:
            return 0.0
        return len(left_tokens & right_tokens) / max(min(len(left_tokens), len(right_tokens)), 1)

    def _text_tokens(self, text: str) -> set[str]:
        ascii_tokens = {item.lower() for item in re.findall(r"[A-Za-z0-9]{2,}", text)}
        chinese_chars = "".join(re.findall(r"[\u4e00-\u9fff]", text))
        chinese_bigrams = {chinese_chars[index : index + 2] for index in range(max(len(chinese_chars) - 1, 0))}
        return {token for token in {*ascii_tokens, *chinese_bigrams} if token}

    def _normalize_text(self, text: str) -> str:
        return re.sub(r"[\s，。！？、,.;:：\-_/]+", "", str(text or "")).strip().lower()

    def _clip(self, text: str, limit: int) -> str:
        value = str(text or "").strip()
        if len(value) <= limit:
            return value
        return value[: max(limit - 1, 0)] + "…"

    def _iso_now(self) -> str:
        return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")

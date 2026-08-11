"""问答 Debugger HTTP 公共接口验收测试。"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

BASE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE_DIR))

from app.api.deps import get_current_user  # noqa: E402
from app.core.database import get_db  # noqa: E402
from app.models import Base, Permission, Role, User  # noqa: E402
from app.services.question_answer_trace_service import QuestionAnswerTraceService  # noqa: E402
from main import app  # noqa: E402


@pytest.fixture()
def api_context() -> tuple[TestClient, Session]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    db = factory()
    menu_permission = Permission(
        module="system:qa-audit",
        action="access",
        code="system:qa-audit",
        description="访问问答审计",
    )
    debug_permission = Permission(
        module="system:qa-audit",
        action="debug",
        code="system:qa-audit:debug",
        description="查看问答 Debugger",
    )
    role = Role(
        name="Debugger",
        code="qa-debugger",
        enabled=True,
        permissions=[menu_permission, debug_permission],
    )
    user = User(username="debugger", password_hash="x", real_name="Debugger", status="enabled", roles=[role])
    db.add(user)
    db.commit()

    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: user
    try:
        yield TestClient(app), db
    finally:
        app.dependency_overrides.clear()
        db.close()
        engine.dispose()


def test_debugger_api_filters_events_by_business_stage(api_context: tuple[TestClient, Session]) -> None:
    """阶段筛选应在分页前生效，并保持总数语义与返回数据一致。"""

    client, db = api_context
    service = QuestionAnswerTraceService(db)
    for sequence, stage in ((1, "question_entry"), (2, "answer_generation"), (3, "result_return")):
        event_type = "trace.completed" if sequence == 3 else ("trace.started" if sequence == 1 else "node.completed")
        service.consume(
            service.build_event(
                trace_id="trace-api-filter",
                event_id=f"event-{sequence}",
                node_id=stage,
                business_stage=stage,
                event_type=event_type,
                sequence=sequence,
                producer="test",
                payload={"stage": stage},
            )
        )
    db.commit()

    response = client.get(
        "/api/system/qa-audits/trace-api-filter/debugger",
        params={"business_stage": "answer_generation", "offset": 0, "limit": 10},
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["events_total"] == 1
    assert [event["business_stage"] for event in data["events"]] == ["answer_generation"]

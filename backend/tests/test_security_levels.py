"""三层密级模型测试。"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

BASE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE_DIR))

from app.core.security_levels import allowed_security_levels, user_max_security_level  # noqa: E402
from app.retrieval.schemas import Evidence  # noqa: E402
from app.services.evidence_access_guard_service import EvidenceAccessGuardService  # noqa: E402


def role(level: str, enabled: bool = True) -> SimpleNamespace:
    """构造只携带密级字段的轻量角色。"""

    return SimpleNamespace(security_level=level, enabled=enabled)


def make_evidence(level: str | None) -> Evidence:
    """构造用于最终证据 guard 的最小 Evidence。"""

    metadata = {} if level is None else {"security_level": level}
    return Evidence(
        score=0.9,
        source_type="project",
        knowledge_base_id=1,
        project_id=1,
        document_id=1,
        chunk_id=1,
        drawing_no=None,
        file_name="source.md",
        page_number=1,
        content="content",
        retriever="keyword",
        metadata=metadata,
    )


def test_user_max_security_level_derives_from_enabled_roles_only() -> None:
    user = SimpleNamespace(
        roles=[
            role("public"),
            role("confidential", enabled=False),
            role("internal"),
        ],
    )

    assert user_max_security_level(None) == "public"
    assert user_max_security_level(SimpleNamespace(roles=[])) == "public"
    assert user_max_security_level(user) == "internal"
    assert allowed_security_levels("internal") == ["public", "internal"]


def test_evidence_guard_rejects_missing_or_over_limit_security_level() -> None:
    guard = EvidenceAccessGuardService(None)
    public_user = SimpleNamespace(roles=[role("public")])

    missing_result = guard.filter_evidences(
        evidences=[make_evidence(None)],
        chat_type="project_chat",
        project_id=1,
        user=public_user,
    )
    denied_result = guard.filter_evidences(
        evidences=[make_evidence("confidential")],
        chat_type="project_chat",
        project_id=1,
        user=public_user,
    )
    allowed_result = guard.filter_evidences(
        evidences=[make_evidence("public")],
        chat_type="project_chat",
        project_id=1,
        user=public_user,
    )

    assert missing_result.rejection_counts == {"security_level_missing": 1}
    assert denied_result.rejection_counts == {"permission_denied": 1}
    assert len(allowed_result.evidences) == 1

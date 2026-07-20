"""敏感内容配置数据访问。"""

from datetime import datetime

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models.sensitive_content import RoleSensitivePermission, SensitiveFilterRule, SensitiveRedactionAudit, SensitiveType
from app.models.user import Role


class SensitiveContentRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def list_types(self, *, enabled_only: bool = False) -> list[SensitiveType]:
        stmt = select(SensitiveType).order_by(SensitiveType.id)
        if enabled_only:
            stmt = stmt.where(SensitiveType.enabled.is_(True))
        return list(self.db.scalars(stmt).all())

    def list_rules(self, *, enabled_only: bool = False) -> list[SensitiveFilterRule]:
        stmt = select(SensitiveFilterRule).order_by(SensitiveFilterRule.priority, SensitiveFilterRule.id)
        if enabled_only:
            stmt = stmt.where(SensitiveFilterRule.enabled.is_(True))
        return list(self.db.scalars(stmt).all())

    def get_type(self, item_id: int) -> SensitiveType | None:
        return self.db.get(SensitiveType, item_id)

    def get_rule(self, item_id: int) -> SensitiveFilterRule | None:
        return self.db.get(SensitiveFilterRule, item_id)

    def add(self, item):
        self.db.add(item)
        self.db.flush()
        return item

    def allowed_types(self, role_ids: set[int]) -> set[str]:
        if not role_ids:
            return set()
        stmt = select(RoleSensitivePermission.sensitive_type_code).where(
            RoleSensitivePermission.role_id.in_(role_ids), RoleSensitivePermission.can_view.is_(True)
        )
        return set(self.db.scalars(stmt).all())

    def list_role_permissions(self, role_id: int) -> list[RoleSensitivePermission]:
        return list(self.db.scalars(select(RoleSensitivePermission).where(RoleSensitivePermission.role_id == role_id)).all())

    def list_roles(self) -> list[Role]:
        return list(self.db.scalars(select(Role).order_by(Role.id)).all())

    def list_audits(
        self,
        *,
        offset: int,
        limit: int,
        started_at: datetime | None = None,
        ended_at: datetime | None = None,
        user_id: int | None = None,
        sensitive_type: str | None = None,
        final_answer_redacted: bool | None = None,
        chat_type: str | None = None,
        project_id: int | None = None,
    ) -> tuple[list[SensitiveRedactionAudit], int]:
        from sqlalchemy import func

        filters = []
        if started_at is not None:
            filters.append(SensitiveRedactionAudit.created_at >= started_at)
        if ended_at is not None:
            filters.append(SensitiveRedactionAudit.created_at <= ended_at)
        if user_id is not None:
            filters.append(SensitiveRedactionAudit.user_id == user_id)
        if sensitive_type:
            filters.append(SensitiveRedactionAudit.redaction_types.like(f'%"{sensitive_type}"%'))
        if final_answer_redacted is not None:
            filters.append(SensitiveRedactionAudit.final_answer_redacted.is_(final_answer_redacted))
        if chat_type:
            filters.append(SensitiveRedactionAudit.chat_type == chat_type)
        if project_id is not None:
            filters.append(SensitiveRedactionAudit.project_id == project_id)
        total_stmt = select(func.count()).select_from(SensitiveRedactionAudit).where(*filters)
        total = int(self.db.scalar(total_stmt) or 0)
        stmt = (
            select(SensitiveRedactionAudit)
            .where(*filters)
            .order_by(SensitiveRedactionAudit.id.desc())
            .offset(offset)
            .limit(limit)
        )
        return list(self.db.scalars(stmt).all()), total

    def replace_role_permissions(self, role_id: int, values: dict[str, bool]) -> None:
        self.db.execute(delete(RoleSensitivePermission).where(RoleSensitivePermission.role_id == role_id))
        for code, can_view in values.items():
            self.db.add(RoleSensitivePermission(role_id=role_id, sensitive_type_code=code, can_view=can_view))

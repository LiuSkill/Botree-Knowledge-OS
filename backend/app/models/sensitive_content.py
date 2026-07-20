"""敏感内容规则、角色授权和脱敏审计模型。"""

from sqlalchemy import Boolean, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class SensitiveType(TimestampMixin, Base):
    __tablename__ = "sensitive_type"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(100), unique=True, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    default_mask_text: Mapped[str] = mapped_column(String(255), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class SensitiveFilterRule(TimestampMixin, Base):
    __tablename__ = "sensitive_filter_rule"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(100), unique=True, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    sensitive_type_code: Mapped[str] = mapped_column(ForeignKey("sensitive_type.code"), index=True, nullable=False)
    match_type: Mapped[str] = mapped_column(String(30), nullable=False)
    pattern: Mapped[str] = mapped_column(Text, nullable=False)
    context_keywords: Mapped[str | None] = mapped_column(Text, nullable=True)
    window_size: Mapped[int] = mapped_column(Integer, default=30, nullable=False)
    mask_text: Mapped[str | None] = mapped_column(String(255), nullable=True)
    priority: Mapped[int] = mapped_column(Integer, default=100, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)


class RoleSensitivePermission(TimestampMixin, Base):
    __tablename__ = "role_sensitive_permission"
    __table_args__ = (UniqueConstraint("role_id", "sensitive_type_code", name="uq_role_sensitive_permission"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    role_id: Mapped[int] = mapped_column(ForeignKey("roles.id", ondelete="CASCADE"), index=True, nullable=False)
    sensitive_type_code: Mapped[str] = mapped_column(ForeignKey("sensitive_type.code"), nullable=False)
    can_view: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class SensitiveRedactionAudit(TimestampMixin, Base):
    __tablename__ = "sensitive_redaction_audit"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True, nullable=True)
    role_ids: Mapped[str] = mapped_column(Text, nullable=False)
    message_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    chat_type: Mapped[str] = mapped_column(String(30), nullable=False)
    project_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    redaction_types: Mapped[str] = mapped_column(Text, nullable=False)
    redaction_count: Mapped[int] = mapped_column(Integer, nullable=False)
    final_answer_redacted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

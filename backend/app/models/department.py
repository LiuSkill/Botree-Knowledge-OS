"""Department models."""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin


class Department(TimestampMixin, Base):
    """企业组织部门。"""

    __tablename__ = "departments"
    __table_args__ = (
        UniqueConstraint("code", name="uk_departments_code"),
        Index("idx_departments_parent_id", "parent_id"),
        Index("idx_departments_status", "status"),
        Index("idx_departments_is_deleted", "is_deleted"),
        {"comment": "部门表"},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True, comment="主键ID")
    name: Mapped[str] = mapped_column(String(100), nullable=False, comment="部门名称")
    code: Mapped[str] = mapped_column(String(100), nullable=False, comment="部门编码")
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("departments.id"), nullable=True, comment="上级部门ID")
    leader_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, comment="部门负责人用户ID")
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False, comment="排序值，数值越小越靠前")
    status: Mapped[str] = mapped_column(String(30), default="enabled", nullable=False, comment="状态：enabled/disabled")
    description: Mapped[str | None] = mapped_column(Text, nullable=True, comment="备注")
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, comment="是否删除")
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, comment="删除时间")

    parent: Mapped["Department | None"] = relationship("Department", remote_side=[id], back_populates="children")
    children: Mapped[list["Department"]] = relationship("Department", back_populates="parent")
    leader: Mapped["User | None"] = relationship("User", foreign_keys=[leader_user_id])
    users: Mapped[list["User"]] = relationship("User", foreign_keys="User.department_id", back_populates="department_ref")

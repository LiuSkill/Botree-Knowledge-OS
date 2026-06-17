"""
Operation Log Models

负责：
1. 系统操作日志建模
2. 记录关键业务动作和执行结果
3. 支撑系统管理审计页面
"""

from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class OperationLog(TimestampMixin, Base):
    """
    操作日志表

    职责：
    - 记录登录、上传、审核、解析、问答等关键动作
    - 保存操作对象、IP 和结果，方便排查问题
    """

    __tablename__ = "operation_logs"
    __table_args__ = {"comment": "操作日志表"}

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True, comment="主键ID")
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, comment="操作用户ID，关联users.id")
    username: Mapped[str | None] = mapped_column(String(100), nullable=True, comment="操作用户名")
    action: Mapped[str] = mapped_column(String(100), nullable=False, comment="操作动作")
    target_type: Mapped[str] = mapped_column(String(100), nullable=False, comment="操作对象类型")
    target_id: Mapped[str | None] = mapped_column(String(100), nullable=True, comment="操作对象ID")
    detail: Mapped[str | None] = mapped_column(Text, nullable=True, comment="操作详情")
    ip_address: Mapped[str | None] = mapped_column(String(100), nullable=True, comment="IP地址")
    result: Mapped[str] = mapped_column(String(30), default="success", nullable=False, comment="执行结果：success/failed")

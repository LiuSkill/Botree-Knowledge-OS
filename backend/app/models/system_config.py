"""
System Configuration Model

负责：
1. 系统配置项建模
2. 保存可调整的平台级配置
3. 为后续功能开关预留扩展空间
"""

from sqlalchemy import Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class SystemConfig(TimestampMixin, Base):
    """
    系统配置表

    职责：
    - 保存 key/value 形式的系统参数
    - 支持后续管理端动态配置
    """

    __tablename__ = "system_configs"
    __table_args__ = {"comment": "系统配置表"}

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True, comment="主键ID")
    config_key: Mapped[str] = mapped_column(String(150), unique=True, nullable=False, comment="配置键")
    config_value: Mapped[str | None] = mapped_column(Text, nullable=True, comment="配置值")
    description: Mapped[str | None] = mapped_column(String(500), nullable=True, comment="配置说明")

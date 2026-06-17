"""
SQLAlchemy Base Model

负责：
1. 定义 ORM 基类
2. 提供 created_at / updated_at 通用字段
3. 统一数据库模型基础行为
"""

from datetime import datetime

from sqlalchemy import DateTime
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """
    ORM 基类

    职责：
    - 作为所有 SQLAlchemy 模型的共同父类
    - 统一 metadata，便于创建表和生成迁移
    """


class TimestampMixin:
    """
    时间戳混入

    职责：
    - 为企业级表统一提供创建时间和更新时间
    - 满足数据库规范中所有表必须具备时间字段的要求
    """

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        nullable=False,
        comment="创建时间",
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
        comment="更新时间",
    )

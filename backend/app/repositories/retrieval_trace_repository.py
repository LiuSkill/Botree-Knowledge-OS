"""
Retrieval Trace Repository

负责：
1. 保存在线检索问答审计记录
2. 查询消息级和系统级检索 Trace
3. 为系统管理页提供可诊断数据
4. 支持文档删除时清理关联检索审计
"""

from __future__ import annotations

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models.retrieval_trace import RetrievalTrace


class RetrievalTraceRepository:
    """
    检索审计仓储

    职责：
    - 写入 retrieval_traces 表
    - 按消息或系统维度查询检索链路
    - 在文档删除时清理引用该文档的检索审计
    """

    def __init__(self, db: Session) -> None:
        self.db = db

    def add(self, trace: RetrievalTrace) -> RetrievalTrace:
        """新增检索审计记录。"""

        self.db.add(trace)
        self.db.flush()
        return trace

    def list_recent(self, limit: int = 200) -> list[RetrievalTrace]:
        """查询最近的检索审计记录。"""

        return list(self.db.scalars(select(RetrievalTrace).order_by(RetrievalTrace.id.desc()).limit(limit)).all())

    def get_by_message(self, message_id: int) -> RetrievalTrace | None:
        """按助手消息ID查询检索审计。"""

        stmt = select(RetrievalTrace).where(RetrievalTrace.message_id == message_id).order_by(RetrievalTrace.id.desc())
        return self.db.scalar(stmt)

    def clear_by_message_ids(self, message_ids: list[int]) -> int:
        """
        物理删除与指定助手消息关联的检索审计。

        参数:
            message_ids: 助手消息ID列表。

        返回:
            删除的审计记录数量。
        """

        if not message_ids:
            return 0
        result = self.db.execute(delete(RetrievalTrace).where(RetrievalTrace.message_id.in_(message_ids)))
        self.db.flush()
        return int(result.rowcount or 0)

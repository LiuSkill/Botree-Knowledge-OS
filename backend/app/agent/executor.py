"""
Agent Executor

负责：
1. 编排检索和回答生成
2. 形成 Agent 执行过程
3. 返回答案、引用来源和检索器信息
"""

from typing import Any

from sqlalchemy.orm import Session

from app.langgraph import RetrievalGraph
from app.models.user import User


class AgentExecutor:
    """
    智能体执行器

    职责：
    - 调用检索路由器
    - 调用回答生成器
    - 汇总引用来源和执行轨迹
    """

    def __init__(self, db: Session) -> None:
        self.db = db
        self.retrieval_graph = RetrievalGraph(db)

    def run(
        self,
        question: str,
        chat_type: str,
        mode: str,
        project_id: int | None,
        user: User,
        *,
        turn_context: Any | None = None,
    ) -> dict:
        """
        执行知识问答

        参数:
            question: 用户问题
            chat_type: 问答类型
            mode: 问答模式
            project_id: 项目ID
            user: 当前用户

        返回:
            Agent 执行结果。
        """

        return self.retrieval_graph.run(question, chat_type, mode, project_id, user, turn_context=turn_context)

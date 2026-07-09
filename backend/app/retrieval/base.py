"""
Retriever Base Class

负责：
1. 定义检索器接口
2. 让 Keyword、Database、Milvus 等检索器保持一致调用方式
3. 降低检索路由耦合
"""

from abc import ABC, abstractmethod

from app.models.user import User
from app.retrieval.schemas import Evidence

DEFAULT_RETRIEVER_TOP_K = 20


class BaseRetriever(ABC):
    """
    检索器抽象基类

    职责：
    - 定义 search 方法
    - 约束检索器返回 Evidence 列表
    """

    name: str

    @abstractmethod
    def search(
        self,
        query: str,
        mode: str,
        project_id: int | None,
        user: User,
        limit: int = DEFAULT_RETRIEVER_TOP_K,
    ) -> list[Evidence]:
        """
        执行检索

        参数:
            query: 查询文本
            mode: 检索模式
            project_id: 项目ID
            user: 当前用户
            limit: 返回数量

        返回:
            证据列表。
        """

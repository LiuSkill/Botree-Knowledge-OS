"""
LangGraph Integration

负责：
1. 暴露在线检索问答编排入口
2. 隔离外部 langgraph 依赖
3. 保持 AgentExecutor 对上层接口兼容
"""

from app.langgraph.retrieval_graph import RetrievalGraph

__all__ = ["RetrievalGraph"]

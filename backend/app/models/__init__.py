"""
Model Registry

负责：
1. 汇总所有 ORM 模型
2. 保证 SQLAlchemy create_all 能识别全部表
3. 为服务层提供统一模型导入入口
"""

from app.models.base import Base
from app.models.chat import ChatCitation, ChatMessage, ChatSession
from app.models.document_asset import DocumentAsset
from app.models.document import Document, DocumentChunk, DocumentVersion
from app.models.graph import GraphEntity, GraphRelation
from app.models.index_task import IndexTask
from app.models.knowledge_base import KnowledgeBase, KnowledgeBasePermission
from app.models.knowledge_category import KnowledgeCategory
from app.models.model_config import ModelConfig
from app.models.operation_log import OperationLog
from app.models.page_index import DocumentPage, DocumentPageBlock, PageIndex
from app.models.project import Project, ProjectMember
from app.models.retrieval_trace import RetrievalTrace
from app.models.review import ReviewLog, ReviewTask
from app.models.system_config import SystemConfig
from app.models.user import Permission, Role, User, role_permissions, user_roles

__all__ = [
    "Base",
    "ChatCitation",
    "ChatMessage",
    "ChatSession",
    "DocumentAsset",
    "Document",
    "DocumentChunk",
    "DocumentVersion",
    "GraphEntity",
    "GraphRelation",
    "IndexTask",
    "KnowledgeBase",
    "KnowledgeBasePermission",
    "KnowledgeCategory",
    "ModelConfig",
    "OperationLog",
    "DocumentPage",
    "DocumentPageBlock",
    "PageIndex",
    "Permission",
    "Project",
    "ProjectMember",
    "RetrievalTrace",
    "ReviewLog",
    "ReviewTask",
    "Role",
    "SystemConfig",
    "User",
    "role_permissions",
    "user_roles",
]

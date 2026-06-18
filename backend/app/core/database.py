"""
Database Infrastructure

负责：
1. 创建 SQLAlchemy Engine 与 Session
2. 初始化数据库表结构
3. 创建默认管理员、角色、权限和基础知识库
"""

import logging
from collections.abc import Generator

from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings
from app.core.security import hash_password
from app.models import Base
from app.models.knowledge_base import KnowledgeBase
from app.models.knowledge_category import KnowledgeCategory
from app.models.model_config import ModelConfig
from app.models.project import Project
from app.models.user import Permission, Role, User

logger = logging.getLogger(__name__)

settings = get_settings()
database_url = settings.effective_database_url
connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
TASK_MODEL_DEFAULTS = (
    ("intent", "intent_llm_model", "llm"),
    ("planner", "planner_llm_model", "llm"),
    ("evidence_judge_fast", "evidence_judge_fast_model", "llm"),
    ("evidence_judge", "evidence_judge_model", "llm"),
    ("answer_llm", "answer_llm_model", "llm"),
    ("vision_llm", "vision_llm_model", "vision"),
    ("analysis_llm", "analysis_llm_model", "llm"),
)


def ensure_mysql_database_exists() -> None:
    """
    确保 MySQL 数据库存在

    说明:
        仅在使用 MYSQL_* 拆分配置且目标数据库名明确时执行
        CREATE DATABASE IF NOT EXISTS，不删除任何已有数据。
    """

    if not database_url.startswith("mysql") or not settings.mysql_database or not settings.mysql_server_url:
        return
    server_engine = create_engine(settings.mysql_server_url, future=True)
    db_name = settings.mysql_database.replace("`", "``")
    with server_engine.begin() as connection:
        connection.execute(
            text(
                f"CREATE DATABASE IF NOT EXISTS `{db_name}` "
                "DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
            )
        )
    server_engine.dispose()


ensure_mysql_database_exists()
engine = create_engine(database_url, connect_args=connect_args, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


def get_db() -> Generator[Session, None, None]:
    """
    获取数据库会话

    返回:
        SQLAlchemy Session，接口请求结束后自动关闭。
    """

    db = SessionLocal()
    try:
        yield db
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def init_database() -> None:
    """
    初始化数据库

    说明:
    - MVP 使用 create_all 保证本地可直接运行。
    - 生产环境后续建议切换 Alembic 迁移。
    """

    # 导入模型注册表后再 create_all，确保所有表都被 metadata 识别。
    Base.metadata.create_all(bind=engine)
    migrate_database()
    with SessionLocal() as db:
        seed_permissions(db)
        admin_role = seed_roles(db)
        seed_admin_user(db, admin_role)
        seed_base_knowledge(db)
        seed_base_categories(db)
        seed_project_categories(db)
        seed_model_config(db)
        db.commit()
    logger.info("数据库初始化完成")


def migrate_database() -> None:
    """
    执行轻量级兼容迁移

    说明:
    - MVP 阶段仍使用 create_all 快速启动。
    - 已存在数据库不会因模型新增字段自动变更，因此这里补充非破坏性 ALTER。
    - 生产环境后续建议切换 Alembic 管理迁移。
    """

    inspector = inspect(engine)
    table_names = inspector.get_table_names()
    if "chat_sessions" not in table_names:
        return

    with engine.begin() as connection:
        chat_columns = {column["name"] for column in inspector.get_columns("chat_sessions")}
        if "chat_type" not in chat_columns:
            alter_sql = (
                "ALTER TABLE chat_sessions ADD COLUMN chat_type VARCHAR(30) NOT NULL "
                "DEFAULT 'base_chat' COMMENT '问答类型：project_chat/base_chat'"
                if database_url.startswith("mysql")
                else "ALTER TABLE chat_sessions ADD COLUMN chat_type VARCHAR(30) NOT NULL DEFAULT 'base_chat'"
            )
            connection.execute(text(alter_sql))
            connection.execute(text("UPDATE chat_sessions SET chat_type = 'project_chat' WHERE project_id IS NOT NULL"))
            logger.info("数据库迁移完成: chat_sessions.chat_type")

        if "documents" in table_names:
            document_columns = {column["name"] for column in inspector.get_columns("documents")}
            _add_column_if_missing(
                connection,
                document_columns,
                "documents",
                "category_id",
                "INTEGER COMMENT '知识分类ID，关联knowledge_categories.id'",
                "INTEGER",
            )
            _add_column_if_missing(
                connection,
                document_columns,
                "documents",
                "document_status",
                "VARCHAR(30) NOT NULL DEFAULT 'pending_review' COMMENT '文档状态：pending_review/reviewed/active/inactive/archived'",
                "VARCHAR(30) NOT NULL DEFAULT 'pending_review'",
            )
            _add_column_if_missing(
                connection,
                document_columns,
                "documents",
                "parse_status",
                "VARCHAR(30) NOT NULL DEFAULT 'unparsed' COMMENT '解析状态：unparsed/parsing/success/failed'",
                "VARCHAR(30) NOT NULL DEFAULT 'unparsed'",
            )
            _add_column_if_missing(connection, document_columns, "documents", "parse_started_at", "DATETIME COMMENT '解析开始时间'", "DATETIME")
            _add_column_if_missing(connection, document_columns, "documents", "parse_finished_at", "DATETIME COMMENT '解析完成时间'", "DATETIME")
            _add_column_if_missing(connection, document_columns, "documents", "parse_error", "TEXT COMMENT '解析失败原因'", "TEXT")
            _add_column_if_missing(connection, document_columns, "documents", "parse_log", "TEXT COMMENT '解析日志'", "TEXT")
            _add_column_if_missing(
                connection,
                document_columns,
                "documents",
                "build_started_at",
                "DATETIME COMMENT '解析并构建索引开始时间'",
                "DATETIME",
            )
            _add_column_if_missing(
                connection,
                document_columns,
                "documents",
                "build_finished_at",
                "DATETIME COMMENT '解析并构建索引完成时间'",
                "DATETIME",
            )
            _add_column_if_missing(
                connection,
                document_columns,
                "documents",
                "build_error",
                "TEXT COMMENT '解析并构建索引失败信息'",
                "TEXT",
            )
            _add_column_if_missing(
                connection,
                document_columns,
                "documents",
                "built_by",
                "INTEGER COMMENT '构建操作人ID，关联users.id'",
                "INTEGER",
            )
            _create_index_if_missing(connection, inspector, "documents", "idx_documents_category_id", "category_id")
            _create_index_if_missing(connection, inspector, "documents", "idx_documents_build_status", "index_status")
            _create_index_if_missing(connection, inspector, "documents", "idx_documents_document_status", "document_status")
            _create_index_if_missing(connection, inspector, "documents", "idx_documents_parse_status", "parse_status")

        if "document_versions" in table_names:
            version_columns = {column["name"] for column in inspector.get_columns("document_versions")}
            _add_column_if_missing(
                connection,
                version_columns,
                "document_versions",
                "category_id",
                "INTEGER COMMENT '版本所属知识分类ID，关联knowledge_categories.id'",
                "INTEGER",
            )
            _add_column_if_missing(connection, version_columns, "document_versions", "file_type", "VARCHAR(50) NOT NULL DEFAULT '' COMMENT '文件类型'", "VARCHAR(50) NOT NULL DEFAULT ''")
            _add_column_if_missing(connection, version_columns, "document_versions", "file_size", "INTEGER NOT NULL DEFAULT 0 COMMENT '文件大小，单位字节'", "INTEGER NOT NULL DEFAULT 0")
            _add_column_if_missing(
                connection,
                version_columns,
                "document_versions",
                "version_status",
                "VARCHAR(30) NOT NULL DEFAULT 'draft' COMMENT '版本状态：draft/pending_review/approved/current/historical/inactive/rejected'",
                "VARCHAR(30) NOT NULL DEFAULT 'draft'",
            )
            _add_column_if_missing(
                connection,
                version_columns,
                "document_versions",
                "parse_status",
                "VARCHAR(30) NOT NULL DEFAULT 'unparsed' COMMENT '解析状态：unparsed/parsing/success/failed'",
                "VARCHAR(30) NOT NULL DEFAULT 'unparsed'",
            )
            _add_column_if_missing(connection, version_columns, "document_versions", "parse_started_at", "DATETIME COMMENT '解析开始时间'", "DATETIME")
            _add_column_if_missing(connection, version_columns, "document_versions", "parse_finished_at", "DATETIME COMMENT '解析完成时间'", "DATETIME")
            _add_column_if_missing(connection, version_columns, "document_versions", "parse_error", "TEXT COMMENT '解析失败原因'", "TEXT")
            _add_column_if_missing(connection, version_columns, "document_versions", "parse_log", "TEXT COMMENT '解析日志'", "TEXT")
            _add_column_if_missing(connection, version_columns, "document_versions", "reviewed_by", "INTEGER COMMENT '审核人ID，关联users.id'", "INTEGER")
            _add_column_if_missing(connection, version_columns, "document_versions", "reviewed_at", "DATETIME COMMENT '审核完成时间'", "DATETIME")
            _add_column_if_missing(connection, version_columns, "document_versions", "review_comment", "TEXT COMMENT '审核意见'", "TEXT")
            _add_column_if_missing(connection, version_columns, "document_versions", "build_started_at", "DATETIME COMMENT '索引构建开始时间'", "DATETIME")
            _add_column_if_missing(connection, version_columns, "document_versions", "build_finished_at", "DATETIME COMMENT '索引构建完成时间'", "DATETIME")
            _add_column_if_missing(connection, version_columns, "document_versions", "build_error", "TEXT COMMENT '索引构建失败原因'", "TEXT")
            _create_index_if_missing(connection, inspector, "document_versions", "idx_document_versions_category_id", "category_id")
            _create_index_if_missing(connection, inspector, "document_versions", "idx_document_versions_version_status", "version_status")
            _create_index_if_missing(connection, inspector, "document_versions", "idx_document_versions_parse_status", "parse_status")

        if "review_tasks" in table_names:
            review_task_columns = {column["name"] for column in inspector.get_columns("review_tasks")}
            _add_column_if_missing(connection, review_task_columns, "review_tasks", "version_id", "INTEGER COMMENT '关联文档版本ID，关联document_versions.id'", "INTEGER")
            _add_column_if_missing(connection, review_task_columns, "review_tasks", "version_no", "INTEGER COMMENT '关联文档版本号'", "INTEGER")
            _create_index_if_missing(connection, inspector, "review_tasks", "idx_review_tasks_version_id", "version_id")

        if "review_logs" in table_names:
            review_log_columns = {column["name"] for column in inspector.get_columns("review_logs")}
            _add_column_if_missing(connection, review_log_columns, "review_logs", "version_id", "INTEGER COMMENT '关联文档版本ID，关联document_versions.id'", "INTEGER")
            _add_column_if_missing(connection, review_log_columns, "review_logs", "version_no", "INTEGER COMMENT '关联文档版本号'", "INTEGER")

        if "index_tasks" in table_names:
            index_task_columns = {column["name"] for column in inspector.get_columns("index_tasks")}
            _add_column_if_missing(connection, index_task_columns, "index_tasks", "version_id", "INTEGER COMMENT '关联文档版本ID，关联document_versions.id'", "INTEGER")
            _create_index_if_missing(connection, inspector, "index_tasks", "idx_index_tasks_version_id", "version_id")

        if "document_chunks" in table_names:
            chunk_columns = {column["name"] for column in inspector.get_columns("document_chunks")}
            _add_column_if_missing(
                connection,
                chunk_columns,
                "document_chunks",
                "version_no",
                "INTEGER NOT NULL DEFAULT 1 COMMENT '所属文档版本号'",
                "INTEGER NOT NULL DEFAULT 1",
            )
            _add_column_if_missing(
                connection,
                chunk_columns,
                "document_chunks",
                "chunk_status",
                "VARCHAR(30) NOT NULL DEFAULT 'active' COMMENT 'Chunk状态：active/obsolete'",
                "VARCHAR(30) NOT NULL DEFAULT 'active'",
            )
            _create_index_if_missing(connection, inspector, "document_chunks", "idx_document_chunks_version_no", "version_no")
            _create_index_if_missing(connection, inspector, "document_chunks", "idx_document_chunks_chunk_status", "chunk_status")

        if "document_pages" in table_names:
            page_columns = {column["name"] for column in inspector.get_columns("document_pages")}
            _add_column_if_missing(connection, page_columns, "document_pages", "clean_content", "TEXT COMMENT '清洗后页文本，用于分块和索引'", "TEXT")
            _add_column_if_missing(connection, page_columns, "document_pages", "filtered_content", "TEXT COMMENT '清洗过滤掉的页文本'", "TEXT")
            _add_column_if_missing(connection, page_columns, "document_pages", "cleaning_metadata_json", "TEXT COMMENT '解析清洗摘要JSON'", "TEXT")

        if "document_page_blocks" in table_names:
            block_columns = {column["name"] for column in inspector.get_columns("document_page_blocks")}
            _add_column_if_missing(connection, block_columns, "document_page_blocks", "clean_text", "TEXT COMMENT '清洗后块文本'", "TEXT")
            _add_column_if_missing(
                connection,
                block_columns,
                "document_page_blocks",
                "filter_status",
                "VARCHAR(30) NOT NULL DEFAULT 'kept' COMMENT '清洗状态：kept/filtered'",
                "VARCHAR(30) NOT NULL DEFAULT 'kept'",
            )
            _add_column_if_missing(connection, block_columns, "document_page_blocks", "filter_reason", "VARCHAR(100) COMMENT '清洗过滤原因'", "VARCHAR(100)")

        if "chat_citations" in table_names:
            citation_columns = {column["name"] for column in inspector.get_columns("chat_citations")}
            _add_column_if_missing(
                connection,
                citation_columns,
                "chat_citations",
                "drawing_no",
                "VARCHAR(100) COMMENT '图纸编号'",
                "VARCHAR(100)",
            )

        if "chat_messages" in table_names:
            message_columns = {column["name"] for column in inspector.get_columns("chat_messages")}
            _add_column_if_missing(
                connection,
                message_columns,
                "chat_messages",
                "feedback_status",
                "VARCHAR(20) COMMENT '回答反馈状态：like/dislike'",
                "VARCHAR(20)",
            )
            _modify_mysql_column_if_needed(
                connection,
                inspector,
                "chat_messages",
                "agent_trace_json",
                "LONGTEXT COMMENT 'Agent执行过程JSON'",
            )

        if "retrieval_traces" in table_names:
            for column_name, comment in (
                ("sub_queries_json", "查询拆解JSON"),
                ("retriever_hits_json", "各检索器命中数量JSON"),
                ("rerank_result_json", "重排结果JSON"),
                ("citations_json", "最终引用JSON"),
                ("trace_json", "LangGraph执行轨迹JSON"),
            ):
                _modify_mysql_column_if_needed(
                    connection,
                    inspector,
                    "retrieval_traces",
                    column_name,
                    f"LONGTEXT COMMENT '{comment}'",
                )

        if "graph_entities" in table_names:
            entity_columns = {column["name"] for column in inspector.get_columns("graph_entities")}
            _add_column_if_missing(
                connection,
                entity_columns,
                "graph_entities",
                "version_no",
                "INTEGER NOT NULL DEFAULT 1 COMMENT '来源文档版本号'",
                "INTEGER NOT NULL DEFAULT 1",
            )
            _add_column_if_missing(
                connection,
                entity_columns,
                "graph_entities",
                "drawing_no",
                "VARCHAR(100) COMMENT '图纸编号'",
                "VARCHAR(100)",
            )
            _add_column_if_missing(
                connection,
                entity_columns,
                "graph_entities",
                "page_number",
                "INTEGER COMMENT '来源页码'",
                "INTEGER",
            )
            _add_column_if_missing(
                connection,
                entity_columns,
                "graph_entities",
                "status",
                "VARCHAR(30) NOT NULL DEFAULT 'published' COMMENT '实体状态：staging/published/obsolete'",
                "VARCHAR(30) NOT NULL DEFAULT 'published'",
            )
            _create_index_if_missing(connection, inspector, "graph_entities", "idx_graph_entities_version_no", "version_no")
            _create_index_if_missing(connection, inspector, "graph_entities", "idx_graph_entities_drawing_no", "drawing_no")
            _create_index_if_missing(connection, inspector, "graph_entities", "idx_graph_entities_page_number", "page_number")
            _create_index_if_missing(connection, inspector, "graph_entities", "idx_graph_entities_status", "status")

        if "graph_relations" in table_names:
            relation_columns = {column["name"] for column in inspector.get_columns("graph_relations")}
            _add_column_if_missing(
                connection,
                relation_columns,
                "graph_relations",
                "version_no",
                "INTEGER NOT NULL DEFAULT 1 COMMENT '来源文档版本号'",
                "INTEGER NOT NULL DEFAULT 1",
            )
            _add_column_if_missing(
                connection,
                relation_columns,
                "graph_relations",
                "drawing_no",
                "VARCHAR(100) COMMENT '图纸编号'",
                "VARCHAR(100)",
            )
            _add_column_if_missing(
                connection,
                relation_columns,
                "graph_relations",
                "page_number",
                "INTEGER COMMENT '来源页码'",
                "INTEGER",
            )
            _add_column_if_missing(
                connection,
                relation_columns,
                "graph_relations",
                "status",
                "VARCHAR(30) NOT NULL DEFAULT 'published' COMMENT '关系状态：staging/published/obsolete'",
                "VARCHAR(30) NOT NULL DEFAULT 'published'",
            )
            _create_index_if_missing(connection, inspector, "graph_relations", "idx_graph_relations_version_no", "version_no")
            _create_index_if_missing(connection, inspector, "graph_relations", "idx_graph_relations_drawing_no", "drawing_no")
            _create_index_if_missing(connection, inspector, "graph_relations", "idx_graph_relations_page_number", "page_number")
            _create_index_if_missing(connection, inspector, "graph_relations", "idx_graph_relations_status", "status")


def _add_column_if_missing(
    connection,
    existing_columns: set[str],
    table_name: str,
    column_name: str,
    mysql_definition: str,
    sqlite_definition: str,
) -> None:
    """
    按需新增数据库列

    参数:
        connection: SQLAlchemy 连接
        existing_columns: 当前表字段集合
        table_name: 表名
        column_name: 字段名
        mysql_definition: MySQL 字段定义
        sqlite_definition: SQLite 字段定义
    """

    if column_name in existing_columns:
        return
    definition = mysql_definition if database_url.startswith("mysql") else sqlite_definition
    connection.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {definition}"))
    existing_columns.add(column_name)
    logger.info("数据库迁移完成: %s.%s", table_name, column_name)


def _modify_mysql_column_if_needed(
    connection,
    inspector,
    table_name: str,
    column_name: str,
    mysql_definition: str,
) -> None:
    """
    按需调整 MySQL 字段类型。

    说明:
        create_all 不会修改已存在字段；问答 Trace 可能超过 TEXT 的 64KB 字节限制，
        因此旧库需要自动扩展为 LONGTEXT。
    """

    if not database_url.startswith("mysql"):
        return
    columns = {column["name"]: column for column in inspector.get_columns(table_name)}
    column = columns.get(column_name)
    if column is None or "LONGTEXT" in str(column["type"]).upper():
        return
    connection.execute(text(f"ALTER TABLE {table_name} MODIFY COLUMN {column_name} {mysql_definition}"))
    logger.info("数据库迁移完成: %s.%s -> LONGTEXT", table_name, column_name)


def _create_index_if_missing(connection, inspector, table_name: str, index_name: str, column_name: str) -> None:
    """
    按需新增数据库索引

    参数:
        connection: SQLAlchemy 连接
        inspector: 数据库结构检查器
        table_name: 表名
        index_name: 索引名
        column_name: 索引字段名
    """

    index_names = {index["name"] for index in inspector.get_indexes(table_name)}
    if index_name in index_names:
        return
    connection.execute(text(f"CREATE INDEX {index_name} ON {table_name} ({column_name})"))
    logger.info("数据库迁移完成: %s.%s", table_name, index_name)


def seed_permissions(db: Session) -> None:
    """
    初始化权限点

    参数:
        db: 数据库会话
    """

    modules = ["dashboard", "knowledge", "project", "authorization", "ai", "review", "system"]
    actions = ["view", "create", "update", "delete", "review", "auth"]
    existing_codes = {item.code for item in db.scalars(select(Permission)).all()}
    for module in modules:
        for action in actions:
            code = f"{module}:{action}"
            if code not in existing_codes:
                db.add(Permission(module=module, action=action, code=code, description=f"{module}模块{action}权限"))


def seed_roles(db: Session) -> Role:
    """
    初始化默认角色

    参数:
        db: 数据库会话

    返回:
        管理员角色。
    """

    admin_role = db.scalar(select(Role).where(Role.code == "admin"))
    if not admin_role:
        admin_role = Role(name="超级管理员", code="admin", description="拥有平台全部权限", enabled=True)
        db.add(admin_role)
        db.flush()

    engineer_role = db.scalar(select(Role).where(Role.code == "engineer"))
    if not engineer_role:
        db.add(Role(name="知识工程师", code="engineer", description="管理知识库和项目资料", enabled=True))

    viewer_role = db.scalar(select(Role).where(Role.code == "viewer"))
    if not viewer_role:
        db.add(Role(name="只读用户", code="viewer", description="查看已授权知识和项目", enabled=True))

    # 管理员角色默认绑定全部权限，便于系统管理页展示完整矩阵。
    permissions = db.scalars(select(Permission)).all()
    admin_role.permissions = permissions
    return admin_role


def seed_admin_user(db: Session, admin_role: Role) -> None:
    """
    初始化默认管理员账号

    参数:
        db: 数据库会话
        admin_role: 管理员角色
    """

    settings = get_settings()
    admin = db.scalar(select(User).where(User.username == settings.default_admin_username))
    if admin:
        return
    if not settings.default_admin_password:
        logger.warning("未配置DEFAULT_ADMIN_PASSWORD，跳过默认管理员账号创建")
        return

    admin = User(
        username=settings.default_admin_username,
        password_hash=hash_password(settings.default_admin_password),
        real_name=settings.default_admin_real_name,
        email="admin@botree.local",
        department="系统管理部",
        status="enabled",
    )
    admin.roles.append(admin_role)
    db.add(admin)
    logger.info("默认管理员账号已创建: %s", settings.default_admin_username)


def seed_base_knowledge(db: Session) -> None:
    """
    初始化基础知识库

    参数:
        db: 数据库会话
    """

    exists = db.scalar(select(KnowledgeBase).where(KnowledgeBase.code == "base-default"))
    if exists:
        return
    db.add(
        KnowledgeBase(
            name="企业基础知识库",
            code="base-default",
            type="base",
            project_id=None,
            description="企业通用工艺、设备、规范和专家经验知识库",
            visibility="internal",
            enabled=True,
        )
    )


def seed_base_categories(db: Session) -> None:
    """
    初始化企业知识默认分类

    参数:
        db: 数据库会话
    """

    exists = db.scalar(select(KnowledgeCategory).where(KnowledgeCategory.scope_type == "base", KnowledgeCategory.project_id.is_(None)))
    if exists:
        return
    defaults = {
        "工艺技术": ["浸出工艺", "萃取分离", "沉淀结晶", "电化学回收"],
        "实验报告": ["条件优化", "表征分析", "中试验证"],
        "设计规范": ["工艺设计", "设备选型", "安全规范"],
        "标准法规": ["国家标准", "行业标准", "环保法规"],
    }
    _seed_category_tree(db, "base", None, defaults)


def seed_project_categories(db: Session) -> None:
    """
    为已有项目补充默认项目资料分类

    参数:
        db: 数据库会话
    """

    projects = db.scalars(select(Project)).all()
    for project in projects:
        exists = db.scalar(select(KnowledgeCategory).where(KnowledgeCategory.scope_type == "project", KnowledgeCategory.project_id == project.id))
        if exists:
            continue
        _seed_category_tree(
            db,
            "project",
            project.id,
            {
                "设计资料": ["设计输入", "设计计算", "设计评审"],
                "实施资料": ["会议纪要", "现场记录", "变更资料"],
                "交付资料": ["验收资料", "运维手册", "归档文件"],
            },
            created_by=project.created_by,
        )


def _seed_category_tree(
    db: Session,
    scope_type: str,
    project_id: int | None,
    tree: dict[str, list[str]],
    created_by: int | None = None,
) -> None:
    """
    写入默认分类树

    参数:
        db: 数据库会话
        scope_type: 分类范围
        project_id: 项目ID
        tree: 默认分类树
        created_by: 创建人ID
    """

    for group_index, (group_name, child_names) in enumerate(tree.items(), start=1):
        parent = KnowledgeCategory(
            scope_type=scope_type,
            project_id=project_id,
            parent_id=None,
            name=group_name,
            code=f"{scope_type}-{project_id or 'base'}-{group_index}",
            sort_order=group_index * 10,
            enabled=True,
            created_by=created_by,
        )
        db.add(parent)
        db.flush()
        for child_index, child_name in enumerate(child_names, start=1):
            db.add(
                KnowledgeCategory(
                    scope_type=scope_type,
                    project_id=project_id,
                    parent_id=parent.id,
                    name=child_name,
                    code=f"{parent.code}-{child_index}",
                    sort_order=child_index * 10,
                    enabled=True,
                    created_by=created_by,
                )
            )


def seed_model_config(db: Session) -> None:
    """
    初始化默认模型配置

    参数:
        db: 数据库会话
    """

    settings = get_settings()
    exists = db.scalar(select(ModelConfig).where(ModelConfig.model_type == "llm", ModelConfig.is_default.is_(True)))
    api_base = settings.llm_base_url or settings.openai_compatible_base_url
    disabled_providers = {"fallback", "mock", "mork", "dummy", "fake", "demo"}
    if exists:
        logger.info("默认LLM模型配置已存在，跳过初始化")
    elif settings.llm_provider.lower() in disabled_providers:
        logger.warning("LLM_PROVIDER 为禁用的占位供应商，跳过默认模型配置初始化")
    elif not api_base:
        logger.warning("未配置真实LLM API Base，跳过默认模型配置初始化")
    else:
        db.add(
            ModelConfig(
                provider=settings.llm_provider,
                model_name=settings.llm_model,
                api_base=api_base,
                api_key=settings.llm_api_key,
                model_type="llm",
                is_default=True,
                enabled=True,
            )
        )

    for model_type, model_attr, provider_group in TASK_MODEL_DEFAULTS:
        _seed_task_model_config(db, model_type, model_attr, provider_group, disabled_providers)

    embedding_exists = db.scalar(select(ModelConfig).where(ModelConfig.model_type == "embedding", ModelConfig.is_default.is_(True)))
    embedding_base = settings.openai_compatible_base_url or settings.llm_base_url
    if embedding_exists:
        logger.info("默认Embedding模型配置已存在，跳过初始化")
    elif settings.embedding_provider.lower() in disabled_providers:
        logger.warning("未配置真实Embedding供应商，跳过默认Embedding配置初始化")
    elif settings.embedding_provider.lower() == "local" and not settings.embedding_model:
        logger.warning("未配置本地Embedding模型路径，跳过默认Embedding配置初始化")
    elif settings.embedding_provider.lower() == "local":
        db.add(
            ModelConfig(
                provider=settings.embedding_provider,
                model_name=settings.embedding_model,
                api_base=None,
                api_key=None,
                model_type="embedding",
                is_default=True,
                enabled=True,
            )
        )
    elif not embedding_base or not settings.embedding_model:
        logger.warning("未配置真实Embedding API Base或模型名，跳过默认Embedding配置初始化")
    else:
        db.add(
            ModelConfig(
                provider=settings.embedding_provider,
                model_name=settings.embedding_model,
                api_base=embedding_base,
                api_key=settings.openai_api_key or settings.llm_api_key,
                model_type="embedding",
                is_default=True,
                enabled=True,
            )
        )


def _seed_task_model_config(
    db: Session,
    model_type: str,
    model_attr: str,
    provider_group: str,
    disabled_providers: set[str],
) -> None:
    """初始化项目问答任务模型默认配置；已有同类型默认模型时不覆盖管理员配置。"""

    current_settings = get_settings()
    exists = db.scalar(select(ModelConfig).where(ModelConfig.model_type == model_type, ModelConfig.is_default.is_(True)))
    if exists:
        logger.info("默认任务模型配置已存在，跳过初始化: model_type=%s", model_type)
        return

    if provider_group == "vision":
        provider = current_settings.vision_llm_provider
        api_base = current_settings.vision_llm_base_url or current_settings.llm_base_url or current_settings.openai_compatible_base_url
    else:
        provider = current_settings.llm_provider
        api_base = current_settings.llm_base_url or current_settings.openai_compatible_base_url
    model_name = str(getattr(current_settings, model_attr, "") or "").strip()

    if provider.lower() in disabled_providers:
        logger.warning("任务模型供应商为禁用占位配置，跳过初始化: model_type=%s provider=%s", model_type, provider)
        return
    if not model_name:
        logger.warning("任务模型名称为空，跳过初始化: model_type=%s", model_type)
        return

    db.add(
        ModelConfig(
            provider=provider,
            model_name=model_name,
            api_base=api_base,
            api_key=None,
            model_type=model_type,
            is_default=True,
            enabled=True,
        )
    )

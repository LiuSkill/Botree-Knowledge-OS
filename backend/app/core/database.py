"""
Database Infrastructure

负责：
1. 创建 SQLAlchemy Engine 与 Session
2. 初始化数据库表结构
3. 创建默认管理员、角色、权限和基础知识库
"""

import json
import logging
from collections.abc import Generator
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings
from app.core.project_directory_template import DEFAULT_PROJECT_DIRECTORY_TEMPLATE
from app.core.rbac import permission_catalog
from app.core.security import hash_password
from app.core.security_levels import DEFAULT_SECURITY_LEVEL
from app.models import Base
from app.models.department import Department
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
LOCAL_RERANKER_PROVIDERS = {"local", "local_reranker", "bge_local", "qwen_local"}
MODEL_SERVICE_PROVIDERS = {"model_service"}


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
        seed_process_config_defaults(db)
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

    with engine.begin() as connection:
        if "knowledge_base_permissions" in table_names:
            connection.execute(text("DROP TABLE knowledge_base_permissions"))
            logger.info("数据库迁移完成: drop knowledge_base_permissions")
            table_names = [name for name in table_names if name != "knowledge_base_permissions"]

        if "knowledge_bases" in table_names:
            knowledge_base_columns = {column["name"] for column in inspector.get_columns("knowledge_bases")}
            _drop_column_if_exists(connection, knowledge_base_columns, "knowledge_bases", "visibility")

        if "roles" in table_names:
            role_columns = {column["name"] for column in inspector.get_columns("roles")}
            _add_security_level_column(connection, role_columns, "roles", "角色最高密级")
            _add_role_data_scope_column(connection, role_columns)
            connection.execute(
                text(
                    """
                    UPDATE roles
                    SET security_level = CASE
                        WHEN code = 'admin' THEN 'confidential'
                        WHEN code = 'engineer' THEN 'internal'
                        WHEN code = 'viewer' THEN 'public'
                        ELSE COALESCE(NULLIF(security_level, ''), 'internal')
                    END
                    WHERE security_level IS NULL
                       OR security_level = ''
                       OR code IN ('admin', 'engineer', 'viewer')
                    """
                )
            )
            connection.execute(
                text(
                    """
                    UPDATE roles
                    SET data_scope = CASE
                        WHEN code = 'admin' THEN 'all'
                        WHEN code = 'engineer' THEN 'all'
                        WHEN code = 'viewer' THEN 'public_only'
                        ELSE COALESCE(NULLIF(data_scope, ''), 'own')
                    END
                    WHERE data_scope IS NULL
                       OR data_scope = ''
                       OR code IN ('admin', 'engineer', 'viewer')
                    """
                )
            )

        if "projects" in table_names:
            project_columns = {column["name"] for column in inspector.get_columns("projects")}
            _add_security_level_column(connection, project_columns, "projects", "项目密级")
            _add_project_basic_columns(connection, project_columns)
            connection.execute(
                text("UPDATE projects SET security_level = COALESCE(NULLIF(security_level, ''), 'internal') WHERE security_level IS NULL OR security_level = ''")
            )
            connection.execute(
                text(
                    """
                    UPDATE projects
                    SET
                        customer_name = COALESCE(NULLIF(customer_name, ''), client),
                        owner_name = COALESCE(NULLIF(owner_name, ''), manager),
                        project_status = CASE
                            WHEN project_status IS NOT NULL AND project_status != '' THEN project_status
                            WHEN status = 'pending' THEN '待启动'
                            WHEN status = 'completed' THEN '已完成'
                            WHEN status = 'archived' THEN '已暂停'
                            ELSE '进行中'
                        END,
                        is_deleted = COALESCE(is_deleted, 0)
                    """
                )
            )
            _create_index_if_missing(connection, inspector, "projects", "idx_projects_security_level", "security_level")
            _create_index_if_missing(connection, inspector, "projects", "idx_projects_is_deleted", "is_deleted")

        if "knowledge_categories" in table_names:
            category_columns = {column["name"] for column in inspector.get_columns("knowledge_categories")}
            _add_project_directory_columns(connection, category_columns)
            connection.execute(
                text(
                    """
                    UPDATE knowledge_categories
                    SET
                        default_security_level = COALESCE(NULLIF(default_security_level, ''), 'internal'),
                        is_deleted = COALESCE(is_deleted, 0)
                    """
                )
            )
            _create_index_if_missing(connection, inspector, "knowledge_categories", "idx_knowledge_categories_deleted", "is_deleted")

        if "users" in table_names:
            user_columns = {column["name"] for column in inspector.get_columns("users")}
            _add_column_if_missing(
                connection,
                user_columns,
                "users",
                "department_id",
                "INTEGER COMMENT '所属部门ID，关联departments.id'",
                "INTEGER",
            )
            _add_column_if_missing(
                connection,
                user_columns,
                "users",
                "avatar_object_key",
                "VARCHAR(500) COMMENT '头像MinIO对象Key'",
                "VARCHAR(500)",
            )
            _add_column_if_missing(
                connection,
                user_columns,
                "users",
                "avatar_file_name",
                "VARCHAR(255) COMMENT '头像原始文件名'",
                "VARCHAR(255)",
            )
            _add_column_if_missing(
                connection,
                user_columns,
                "users",
                "avatar_content_type",
                "VARCHAR(100) COMMENT '头像文件MIME类型'",
                "VARCHAR(100)",
            )
            _add_column_if_missing(
                connection,
                user_columns,
                "users",
                "avatar_updated_at",
                "DATETIME COMMENT '头像更新时间'",
                "DATETIME",
            )
            _add_column_if_missing(
                connection,
                user_columns,
                "users",
                "is_deleted",
                "BOOLEAN NOT NULL DEFAULT FALSE COMMENT '是否删除'",
                "BOOLEAN NOT NULL DEFAULT 0",
            )
            _add_column_if_missing(
                connection,
                user_columns,
                "users",
                "deleted_at",
                "DATETIME COMMENT '删除时间'",
                "DATETIME",
            )
            connection.execute(text("UPDATE users SET is_deleted = COALESCE(is_deleted, 0)"))
            _create_index_if_missing(connection, inspector, "users", "idx_users_department_id", "department_id")
            _create_index_if_missing(connection, inspector, "users", "idx_users_is_deleted", "is_deleted")

        if "chat_sessions" not in table_names:
            return

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
            _add_security_level_column(connection, document_columns, "documents", "文档密级")
            connection.execute(
                text("UPDATE documents SET security_level = COALESCE(NULLIF(security_level, ''), 'internal') WHERE security_level IS NULL OR security_level = ''")
            )
            _add_document_metadata_columns(connection, document_columns)
            _create_index_if_missing(connection, inspector, "documents", "idx_documents_category_id", "category_id")
            _create_index_if_missing(connection, inspector, "documents", "idx_documents_directory_id", "directory_id")
            _create_index_if_missing(connection, inspector, "documents", "idx_documents_build_status", "index_status")
            _create_index_if_missing(connection, inspector, "documents", "idx_documents_document_status", "document_status")
            _create_index_if_missing(connection, inspector, "documents", "idx_documents_status", "status")
            _create_index_if_missing(connection, inspector, "documents", "idx_documents_parse_status", "parse_status")
            _create_index_if_missing(connection, inspector, "documents", "idx_documents_security_level", "security_level")
            _create_index_if_missing(connection, inspector, "documents", "idx_documents_is_current_version", "is_current_version")
            _create_index_if_missing(connection, inspector, "documents", "idx_documents_is_deleted", "is_deleted")

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
            _add_security_level_column(connection, version_columns, "document_versions", "文档版本密级")
            connection.execute(
                text(
                    """
                    UPDATE document_versions
                    SET security_level = COALESCE(
                        (SELECT documents.security_level FROM documents WHERE documents.id = document_versions.document_id),
                        'internal'
                    )
                    WHERE security_level IS NULL OR security_level = ''
                    """
                )
            )
            _add_document_version_metadata_columns(connection, version_columns)
            _create_index_if_missing(connection, inspector, "document_versions", "idx_document_versions_category_id", "category_id")
            _create_index_if_missing(connection, inspector, "document_versions", "idx_document_versions_project_id", "project_id")
            _create_index_if_missing(connection, inspector, "document_versions", "idx_document_versions_version_status", "version_status")
            _create_index_if_missing(connection, inspector, "document_versions", "idx_document_versions_status", "status")
            _create_index_if_missing(connection, inspector, "document_versions", "idx_document_versions_parse_status", "parse_status")
            _create_index_if_missing(connection, inspector, "document_versions", "idx_document_versions_security_level", "security_level")
            _create_index_if_missing(connection, inspector, "document_versions", "idx_document_versions_current", "is_current_version")

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
            _add_security_level_column(connection, chunk_columns, "document_chunks", "Chunk密级")
            connection.execute(
                text(
                    """
                    UPDATE document_chunks
                    SET security_level = COALESCE(
                        (SELECT documents.security_level FROM documents WHERE documents.id = document_chunks.document_id),
                        'internal'
                    )
                    WHERE security_level IS NULL OR security_level = ''
                    """
                )
            )
            _create_index_if_missing(connection, inspector, "document_chunks", "idx_document_chunks_version_no", "version_no")
            _create_index_if_missing(connection, inspector, "document_chunks", "idx_document_chunks_chunk_status", "chunk_status")
            _create_index_if_missing(connection, inspector, "document_chunks", "idx_document_chunks_security_level", "security_level")

        if "document_pages" in table_names:
            page_columns = {column["name"] for column in inspector.get_columns("document_pages")}
            _add_column_if_missing(connection, page_columns, "document_pages", "clean_content", "LONGTEXT COMMENT '清洗后页文本，用于分块和索引'", "TEXT")
            _add_column_if_missing(connection, page_columns, "document_pages", "filtered_content", "LONGTEXT COMMENT '清洗过滤掉的页文本'", "TEXT")
            _add_column_if_missing(connection, page_columns, "document_pages", "cleaning_metadata_json", "LONGTEXT COMMENT '解析清洗摘要JSON'", "TEXT")
            for column_name, definition in (
                ("page_text", "LONGTEXT NOT NULL COMMENT '页原始正文文本'"),
                ("clean_content", "LONGTEXT COMMENT '清洗后页文本'"),
                ("filtered_content", "LONGTEXT COMMENT '过滤后页文本'"),
                ("cleaning_metadata_json", "LONGTEXT COMMENT '清洗摘要JSON'"),
                ("corrected_text", "LONGTEXT COMMENT '人工修正后的文本'"),
            ):
                _modify_mysql_column_if_needed(connection, inspector, "document_pages", column_name, definition)

            _add_security_level_column(connection, page_columns, "document_pages", "文档页密级")
            connection.execute(
                text(
                    """
                    UPDATE document_pages
                    SET security_level = COALESCE(
                        (SELECT documents.security_level FROM documents WHERE documents.id = document_pages.document_id),
                        'internal'
                    )
                    WHERE security_level IS NULL OR security_level = ''
                    """
                )
            )
            _create_index_if_missing(connection, inspector, "document_pages", "idx_document_pages_security_level", "security_level")

        if "page_indexes" in table_names:
            page_index_columns = {column["name"] for column in inspector.get_columns("page_indexes")}
            _modify_mysql_column_if_needed(
                connection,
                inspector,
                "page_indexes",
                "index_text",
                "LONGTEXT NOT NULL COMMENT '用于页面索引的文本'",
            )
            _add_security_level_column(connection, page_index_columns, "page_indexes", "PageIndex密级")
            connection.execute(
                text(
                    """
                    UPDATE page_indexes
                    SET security_level = COALESCE(
                        (SELECT documents.security_level FROM documents WHERE documents.id = page_indexes.document_id),
                        'internal'
                    )
                    WHERE security_level IS NULL OR security_level = ''
                    """
                )
            )
            _create_index_if_missing(connection, inspector, "page_indexes", "idx_page_indexes_security_level", "security_level")
            _create_composite_index_if_missing(
                connection,
                inspector,
                "page_indexes",
                "idx_page_indexes_doc_status_ver",
                ("document_id", "status", "version_no"),
            )

        if "document_page_blocks" in table_names:
            block_columns = {column["name"] for column in inspector.get_columns("document_page_blocks")}
            _add_column_if_missing(connection, block_columns, "document_page_blocks", "clean_text", "LONGTEXT COMMENT '清洗后块文本'", "TEXT")
            _add_column_if_missing(
                connection,
                block_columns,
                "document_page_blocks",
                "filter_status",
                "VARCHAR(30) NOT NULL DEFAULT 'kept' COMMENT '清洗状态：kept/filtered'",
                "VARCHAR(30) NOT NULL DEFAULT 'kept'",
            )
            _add_column_if_missing(connection, block_columns, "document_page_blocks", "filter_reason", "VARCHAR(100) COMMENT '清洗过滤原因'", "VARCHAR(100)")
            for column_name, definition in (
                ("text", "LONGTEXT COMMENT '块原始文本'"),
                ("clean_text", "LONGTEXT COMMENT '清洗后块文本'"),
                ("metadata_json", "LONGTEXT COMMENT '块扩展元数据JSON'"),
            ):
                _modify_mysql_column_if_needed(connection, inspector, "document_page_blocks", column_name, definition)

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
            _add_column_if_missing(
                connection,
                message_columns,
                "chat_messages",
                "progress_json",
                "LONGTEXT COMMENT '用户可见处理进度JSON'",
                "TEXT",
            )
            _modify_mysql_column_if_needed(
                connection,
                inspector,
                "chat_messages",
                "agent_trace_json",
                "LONGTEXT COMMENT 'Agent执行过程JSON'",
            )
            _modify_mysql_column_if_needed(
                connection,
                inspector,
                "chat_messages",
                "progress_json",
                "LONGTEXT COMMENT '用户可见处理进度JSON'",
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
            _create_composite_index_if_missing(
                connection,
                inspector,
                "graph_entities",
                "idx_graph_entities_doc_status_ver",
                ("document_id", "status", "version_no"),
            )

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
            _create_composite_index_if_missing(
                connection,
                inspector,
                "graph_relations",
                "idx_graph_relations_doc_status_ver",
                ("document_id", "status", "version_no"),
            )

        if "operation_logs" in table_names:
            operation_log_columns = {column["name"] for column in inspector.get_columns("operation_logs")}
            _add_column_if_missing(connection, operation_log_columns, "operation_logs", "project_id", "INTEGER COMMENT '项目ID'", "INTEGER")
            _add_column_if_missing(
                connection,
                operation_log_columns,
                "operation_logs",
                "user_agent",
                "VARCHAR(500) COMMENT 'User-Agent'",
                "VARCHAR(500)",
            )
            _create_index_if_missing(connection, inspector, "operation_logs", "idx_operation_logs_project_id", "project_id")


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


def _add_security_level_column(connection, existing_columns: set[str], table_name: str, comment: str) -> None:
    """为三层密级访问控制补齐 security_level 字段。"""

    _add_column_if_missing(
        connection,
        existing_columns,
        table_name,
        "security_level",
        f"VARCHAR(30) NOT NULL DEFAULT 'internal' COMMENT '{comment}: public/internal/confidential'",
        "VARCHAR(30) NOT NULL DEFAULT 'internal'",
    )


def _add_role_data_scope_column(connection, existing_columns: set[str]) -> None:
    """为角色补齐项目数据范围字段。"""

    _add_column_if_missing(
        connection,
        existing_columns,
        "roles",
        "data_scope",
        "VARCHAR(30) NOT NULL DEFAULT 'own' COMMENT '角色项目数据范围: all/department/own/public_only'",
        "VARCHAR(30) NOT NULL DEFAULT 'own'",
    )


def _add_project_basic_columns(connection, existing_columns: set[str]) -> None:
    """为项目基本信息补齐兼容扩展字段。"""

    column_definitions = [
        ("project_short_name", "VARCHAR(100) COMMENT '项目简称'", "VARCHAR(100)"),
        ("project_english_name", "VARCHAR(255) COMMENT '项目英文名称'", "VARCHAR(255)"),
        ("customer_name", "VARCHAR(255) COMMENT '客户名称'", "VARCHAR(255)"),
        ("project_type", "VARCHAR(100) COMMENT '项目类型'", "VARCHAR(100)"),
        ("project_status", "VARCHAR(30) NOT NULL DEFAULT '进行中' COMMENT '项目状态: 待启动/进行中/已完成/已暂停'", "VARCHAR(30) NOT NULL DEFAULT '进行中'"),
        ("project_stage", "VARCHAR(100) COMMENT '项目阶段'", "VARCHAR(100)"),
        ("raw_material_type", "VARCHAR(255) COMMENT '原料类型'", "VARCHAR(255)"),
        ("capacity", "VARCHAR(255) COMMENT '处理能力'", "VARCHAR(255)"),
        ("process_route", "TEXT COMMENT '工艺路线'", "TEXT"),
        ("main_products", "TEXT COMMENT '主要产品'", "TEXT"),
        ("scope_description", "TEXT COMMENT '项目范围'", "TEXT"),
        ("deliverables", "TEXT COMMENT '交付成果'", "TEXT"),
        ("owner_id", "INTEGER COMMENT '项目负责人ID'", "INTEGER"),
        ("owner_name", "VARCHAR(100) COMMENT '项目负责人姓名'", "VARCHAR(100)"),
        ("department_id", "INTEGER COMMENT '所属部门ID'", "INTEGER"),
        ("is_deleted", "BOOLEAN NOT NULL DEFAULT FALSE COMMENT '是否删除'", "BOOLEAN NOT NULL DEFAULT 0"),
        ("deleted_at", "DATETIME COMMENT '删除时间'", "DATETIME"),
    ]
    for column_name, mysql_definition, sqlite_definition in column_definitions:
        _add_column_if_missing(connection, existing_columns, "projects", column_name, mysql_definition, sqlite_definition)


def _add_project_directory_columns(connection, existing_columns: set[str]) -> None:
    """为项目资料目录补齐默认密级和软删除字段。"""

    column_definitions = [
        (
            "default_security_level",
            "VARCHAR(30) NOT NULL DEFAULT 'internal' COMMENT '目录默认密级'",
            "VARCHAR(30) NOT NULL DEFAULT 'internal'",
        ),
        ("is_deleted", "BOOLEAN NOT NULL DEFAULT FALSE COMMENT '是否删除'", "BOOLEAN NOT NULL DEFAULT 0"),
        ("deleted_at", "DATETIME COMMENT '删除时间'", "DATETIME"),
    ]
    for column_name, mysql_definition, sqlite_definition in column_definitions:
        _add_column_if_missing(
            connection,
            existing_columns,
            "knowledge_categories",
            column_name,
            mysql_definition,
            sqlite_definition,
        )


def _add_document_metadata_columns(connection, existing_columns: set[str]) -> None:
    """为项目资料补齐轻量元数据字段，并从旧字段回填兼容值。"""

    column_definitions = [
        ("directory_id", "INTEGER COMMENT '所属项目资料目录ID'", "INTEGER"),
        ("document_name", "VARCHAR(255) COMMENT '文件名称'", "VARCHAR(255)"),
        ("document_type", "VARCHAR(50) COMMENT '文档类型'", "VARCHAR(50)"),
        ("discipline", "VARCHAR(50) COMMENT '所属专业'", "VARCHAR(50)"),
        ("version", "VARCHAR(50) COMMENT '版本号'", "VARCHAR(50)"),
        ("status", "VARCHAR(30) NOT NULL DEFAULT '待审核' COMMENT '文件状态: 待审核/已发布'", "VARCHAR(30) NOT NULL DEFAULT '待审核'"),
        ("upload_user_id", "INTEGER COMMENT '上传人ID'", "INTEGER"),
        ("file_path", "VARCHAR(500) COMMENT '文件路径'", "VARCHAR(500)"),
        ("preview_url", "VARCHAR(500) COMMENT '预览地址'", "VARCHAR(500)"),
        ("is_current_version", "BOOLEAN NOT NULL DEFAULT TRUE COMMENT '是否当前版本'", "BOOLEAN NOT NULL DEFAULT 1"),
        ("is_deleted", "BOOLEAN NOT NULL DEFAULT FALSE COMMENT '是否删除'", "BOOLEAN NOT NULL DEFAULT 0"),
        ("deleted_at", "DATETIME COMMENT '删除时间'", "DATETIME"),
        ("remark", "TEXT COMMENT '备注'", "TEXT"),
    ]
    for column_name, mysql_definition, sqlite_definition in column_definitions:
        _add_column_if_missing(
            connection,
            existing_columns,
            "documents",
            column_name,
            mysql_definition,
            sqlite_definition,
        )

    version_expr = "CONCAT('v', COALESCE(version_no, 1))" if database_url.startswith("mysql") else "'v' || COALESCE(version_no, 1)"
    connection.execute(
        text(
            f"""
            UPDATE documents
            SET
                document_name = COALESCE(NULLIF(document_name, ''), file_name),
                directory_id = COALESCE(directory_id, category_id),
                file_path = COALESCE(NULLIF(file_path, ''), storage_path),
                version = COALESCE(NULLIF(version, ''), {version_expr}),
                status = CASE
                    WHEN review_status = 'approved' OR document_status IN ('active', 'reviewed') THEN '已发布'
                    WHEN status IN ('待审核', '已发布') THEN status
                    ELSE '待审核'
                END,
                upload_user_id = COALESCE(upload_user_id, created_by),
                is_current_version = COALESCE(is_current_version, current_version, TRUE),
                is_deleted = COALESCE(is_deleted, FALSE)
            """
        )
    )


def _add_document_version_metadata_columns(connection, existing_columns: set[str]) -> None:
    """为文档版本补齐项目资料版本字段，并从旧版本字段回填。"""

    column_definitions = [
        ("project_id", "INTEGER COMMENT '所属项目ID'", "INTEGER"),
        ("version", "VARCHAR(50) COMMENT '版本号'", "VARCHAR(50)"),
        ("file_path", "VARCHAR(500) COMMENT '文件路径'", "VARCHAR(500)"),
        ("status", "VARCHAR(30) NOT NULL DEFAULT '待审核' COMMENT '文件状态: 待审核/已发布'", "VARCHAR(30) NOT NULL DEFAULT '待审核'"),
        ("is_current_version", "BOOLEAN NOT NULL DEFAULT FALSE COMMENT '是否当前版本'", "BOOLEAN NOT NULL DEFAULT 0"),
        ("upload_user_id", "INTEGER COMMENT '上传人ID'", "INTEGER"),
        ("version_note", "TEXT COMMENT '版本备注'", "TEXT"),
    ]
    for column_name, mysql_definition, sqlite_definition in column_definitions:
        _add_column_if_missing(
            connection,
            existing_columns,
            "document_versions",
            column_name,
            mysql_definition,
            sqlite_definition,
        )

    version_expr = "CONCAT('v', COALESCE(version_no, 1))" if database_url.startswith("mysql") else "'v' || COALESCE(version_no, 1)"
    connection.execute(
        text(
            f"""
            UPDATE document_versions
            SET
                project_id = COALESCE(
                    project_id,
                    (SELECT documents.project_id FROM documents WHERE documents.id = document_versions.document_id)
                ),
                version = COALESCE(NULLIF(version, ''), {version_expr}),
                file_path = COALESCE(NULLIF(file_path, ''), storage_path),
                status = CASE
                    WHEN review_status = 'approved' OR version_status IN ('approved', 'current') THEN '已发布'
                    WHEN status IN ('待审核', '已发布') THEN status
                    ELSE '待审核'
                END,
                is_current_version = CASE WHEN is_current = TRUE THEN TRUE ELSE FALSE END,
                upload_user_id = COALESCE(upload_user_id, created_by),
                version_note = COALESCE(version_note, change_summary)
            """
        )
    )


def _drop_column_if_exists(connection, existing_columns: set[str], table_name: str, column_name: str) -> None:
    """彻底移除不再参与访问控制的旧字段。"""

    if column_name not in existing_columns:
        return
    connection.execute(text(f"ALTER TABLE {table_name} DROP COLUMN {column_name}"))
    existing_columns.remove(column_name)
    logger.info("数据库迁移完成: drop %s.%s", table_name, column_name)


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
        create_all 不会修改已存在字段；问答 Trace 与页级解析文本可能超过 TEXT 的 64KB 字节限制，
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


def _create_composite_index_if_missing(
    connection,
    inspector,
    table_name: str,
    index_name: str,
    column_names: tuple[str, ...],
) -> None:
    """
    按需新增复合索引，避免索引发布时走 status 单列索引扫描大量已发布行。
    """

    index_names = {index["name"] for index in inspector.get_indexes(table_name)}
    if index_name in index_names:
        return
    columns_sql = ", ".join(column_names)
    connection.execute(text(f"CREATE INDEX {index_name} ON {table_name} ({columns_sql})"))
    logger.info("数据库迁移完成: %s.%s", table_name, index_name)


def seed_permissions(db: Session) -> None:
    """
    初始化权限点

    参数:
        db: 数据库会话
    """

    catalog = permission_catalog()
    catalog_by_code = {item["code"]: item for item in catalog}
    existing_by_code = {item.code: item for item in db.scalars(select(Permission)).all()}

    for code, item in catalog_by_code.items():
        permission = existing_by_code.get(code)
        if permission is None:
            db.add(Permission(**item))
            continue
        permission.module = item["module"]
        permission.action = item["action"]
        permission.description = item["description"]

    # 旧权限不再对应真实菜单或按钮，先断开角色关联再删除，避免权限矩阵继续写回废弃 key。
    obsolete_permissions = [permission for code, permission in existing_by_code.items() if code not in catalog_by_code]
    for permission in obsolete_permissions:
        permission.roles.clear()
        db.delete(permission)


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
        admin_role = Role(name="超级管理员", code="admin", description="拥有平台全部权限", enabled=True, security_level="confidential")
        db.add(admin_role)
        db.flush()
    else:
        admin_role.security_level = "confidential"
    admin_role.data_scope = "all"

    engineer_role = db.scalar(select(Role).where(Role.code == "engineer"))
    if not engineer_role:
        db.add(Role(name="知识工程师", code="engineer", description="管理知识库和项目资料", enabled=True, security_level="internal"))
    else:
        engineer_role.security_level = "internal"
    db.flush()
    engineer_role = db.scalar(select(Role).where(Role.code == "engineer"))
    if engineer_role:
        engineer_role.data_scope = "all"

    viewer_role = db.scalar(select(Role).where(Role.code == "viewer"))
    if not viewer_role:
        db.add(Role(name="只读用户", code="viewer", description="查看已授权知识和项目", enabled=True, security_level="public"))
    else:
        viewer_role.security_level = "public"
    db.flush()
    viewer_role = db.scalar(select(Role).where(Role.code == "viewer"))
    if viewer_role:
        viewer_role.data_scope = "public_only"

    # 管理员角色默认绑定全部权限，便于系统管理页展示完整矩阵。
    permissions = db.scalars(select(Permission)).all()
    admin_role.permissions = permissions
    return admin_role


def seed_default_department(db: Session) -> None:
    """初始化默认部门。"""

    department = db.scalar(select(Department).where(Department.code == "DEFAULT"))
    if department:
        department.name = "默认部门"
        department.parent_id = None
        department.status = "enabled"
        department.is_deleted = False
        department.deleted_at = None
        return
    db.add(
        Department(
            name="默认部门",
            code="DEFAULT",
            parent_id=None,
            leader_user_id=None,
            sort_order=0,
            status="enabled",
            description="系统初始化默认部门",
            is_deleted=False,
        )
    )


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
        _seed_project_directory_template(db, project.id, created_by=project.created_by)


def _seed_project_directory_template(db: Session, project_id: int, created_by: int | None = None) -> None:
    """按统一项目资料目录模板为项目写入默认目录。"""

    for group_index, (group_code, group_name, child_items) in enumerate(DEFAULT_PROJECT_DIRECTORY_TEMPLATE, start=1):
        parent = KnowledgeCategory(
            scope_type="project",
            project_id=project_id,
            parent_id=None,
            name=group_name,
            code=group_code,
            sort_order=group_index * 100,
            enabled=True,
            default_security_level=DEFAULT_SECURITY_LEVEL,
            is_deleted=False,
            created_by=created_by,
        )
        db.add(parent)
        db.flush()
        for child_index, (child_code, child_name) in enumerate(child_items, start=1):
            db.add(
                KnowledgeCategory(
                    scope_type="project",
                    project_id=project_id,
                    parent_id=parent.id,
                    name=child_name,
                    code=child_code,
                    sort_order=group_index * 100 + child_index,
                    enabled=True,
                    default_security_level=DEFAULT_SECURITY_LEVEL,
                    is_deleted=False,
                    created_by=created_by,
                )
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
    embedding_provider = str(settings.embedding_provider or "").strip()
    embedding_provider_key = embedding_provider.lower()
    embedding_model = str(settings.embedding_model or settings.model_service_embedding_model or "").strip()
    embedding_base = (
        settings.embedding_api_base
        or (settings.model_service_api_base if embedding_provider_key in MODEL_SERVICE_PROVIDERS else None)
        or settings.openai_compatible_base_url
        or settings.llm_base_url
    )
    embedding_api_key = (
        settings.embedding_api_key
        or (settings.model_service_api_key if embedding_provider_key in MODEL_SERVICE_PROVIDERS else None)
        or settings.openai_api_key
        or settings.llm_api_key
    )
    if embedding_exists:
        logger.info("默认Embedding模型配置已存在，跳过初始化")
    elif embedding_provider_key in disabled_providers:
        logger.warning("未配置真实Embedding供应商，跳过默认Embedding配置初始化")
    elif embedding_provider_key == "local" and not embedding_model:
        logger.warning("未配置本地Embedding模型路径，跳过默认Embedding配置初始化")
    elif embedding_provider_key == "local":
        db.add(
            ModelConfig(
                provider=embedding_provider,
                model_name=embedding_model,
                api_base=None,
                api_key=None,
                model_type="embedding",
                is_default=True,
                enabled=True,
            )
        )
    elif not embedding_base or not embedding_model:
        logger.warning("未配置真实Embedding API Base或模型名，跳过默认Embedding配置初始化")
    else:
        db.add(
            ModelConfig(
                provider=embedding_provider,
                model_name=embedding_model,
                api_base=embedding_base,
                api_key=embedding_api_key,
                model_type="embedding",
                is_default=True,
                enabled=True,
            )
        )
    _seed_default_reranker_config(db, disabled_providers)


def seed_process_config_defaults(db: Session) -> None:
    """Seed process configuration defaults when the process configuration module is empty."""

    from app.models.process_config import (
        ProcessCalculationOutput,
        ProcessConsumable,
        ProcessMaterial,
        ProcessMaterialComposition,
        ProcessNode,
        ProcessProduct,
        ProcessPublicService,
        ProcessRegionPrice,
        ProcessRoute,
        ProcessRouteNode,
    )

    seed_models = (ProcessMaterial, ProcessProduct, ProcessConsumable, ProcessPublicService, ProcessNode, ProcessRoute)
    if any(db.scalar(select(model.id).where(model.is_deleted.is_(False)).limit(1)) for model in seed_models):
        logger.info("工艺配置默认数据已存在，跳过初始化")
        return

    defaults_path = Path(__file__).with_name("process_config_defaults.json")
    if not defaults_path.exists():
        logger.warning("工艺配置默认数据文件不存在，跳过初始化: %s", defaults_path)
        return

    data = json.loads(defaults_path.read_text(encoding="utf-8"))
    db.flush()
    admin = db.scalar(select(User).where(User.username == settings.default_admin_username))
    operator_id = admin.id if admin else None

    material_map: dict[str, ProcessMaterial] = {}
    product_map: dict[str, ProcessProduct] = {}
    consumable_map: dict[str, ProcessConsumable] = {}
    service_map: dict[str, ProcessPublicService] = {}
    node_map: dict[str, ProcessNode] = {}

    def add_region_prices(owner_type: str, owner_id: int, rows: list[dict[str, Any]]) -> None:
        for row in rows:
            db.add(
                ProcessRegionPrice(
                    owner_type=owner_type,
                    owner_id=owner_id,
                    region_code=row["region_code"],
                    region_name=row["region_name"],
                    currency=row["currency"],
                    unit_price=_seed_decimal(row.get("unit_price")),
                    unit=row["unit"],
                    status=row.get("status") or "enabled",
                    created_by=operator_id,
                    updated_by=operator_id,
                    is_deleted=False,
                )
            )

    for row in data.get("materials", []):
        item = ProcessMaterial(**_seed_library_fields(row), created_by=operator_id, updated_by=operator_id, is_deleted=False)
        db.add(item)
        db.flush()
        material_map[item.code] = item
        add_region_prices("material", item.id, row.get("region_prices", []))
        for comp in row.get("compositions", []):
            db.add(
                ProcessMaterialComposition(
                    material_id=item.id,
                    element_code=comp["element_code"],
                    element_name=comp["element_name"],
                    content_ratio=_seed_decimal(comp.get("content_ratio")),
                    unit=comp.get("unit") or "%",
                    remark=comp.get("remark"),
                    created_by=operator_id,
                    updated_by=operator_id,
                    is_deleted=False,
                )
            )

    for row in data.get("products", []):
        item = ProcessProduct(
            **_seed_library_fields(row),
            output_type=row.get("output_type") or "product",
            spec=row.get("spec"),
            treatment_cost=_seed_decimal(row.get("treatment_cost")),
            created_by=operator_id,
            updated_by=operator_id,
            is_deleted=False,
        )
        db.add(item)
        db.flush()
        product_map[item.code] = item
        add_region_prices("product", item.id, row.get("region_prices", []))

    for row in data.get("consumables", []):
        item = ProcessConsumable(**_seed_library_fields(row), created_by=operator_id, updated_by=operator_id, is_deleted=False)
        db.add(item)
        db.flush()
        consumable_map[item.code] = item
        add_region_prices("consumable", item.id, row.get("region_prices", []))

    for row in data.get("public_services", []):
        item = ProcessPublicService(**_seed_library_fields(row), created_by=operator_id, updated_by=operator_id, is_deleted=False)
        db.add(item)
        db.flush()
        service_map[item.code] = item
        add_region_prices("public_service", item.id, row.get("region_prices", []))

    for row in data.get("nodes", []):
        node = ProcessNode(
            code=row["code"],
            name=row["name"],
            node_type=row["node_type"],
            staff=_seed_decimal(row.get("staff")),
            area=_seed_decimal(row.get("area")),
            description=row.get("description"),
            status=row.get("status") or "enabled",
            version=row.get("version") or "V1",
            sort_order=int(row.get("sort_order") or 0),
            remark=row.get("remark"),
            created_by=operator_id,
            updated_by=operator_id,
            is_deleted=False,
        )
        db.add(node)
        db.flush()
        node_map[node.code] = node
        _seed_process_node_children(db, node, row, material_map, product_map, consumable_map, service_map)

    for row in data.get("routes", []):
        material = material_map.get(row.get("input_material_code"))
        product = product_map.get(row.get("final_product_code"))
        if material is None or product is None:
            logger.warning("跳过工艺路线默认数据，原料或最终产品不存在: route_code=%s", row.get("code"))
            continue
        route = ProcessRoute(
            code=row["code"],
            name=row["name"],
            input_material_id=material.id,
            final_product_id=product.id,
            version=row.get("version") or "V1",
            description=row.get("description"),
            status=row.get("status") or "enabled",
            sort_order=int(row.get("sort_order") or 0),
            remark=row.get("remark"),
            created_by=operator_id,
            updated_by=operator_id,
            is_deleted=False,
        )
        db.add(route)
        db.flush()
        for child in row.get("nodes", []):
            child_node = node_map.get(child.get("node_code"))
            if child_node is None:
                logger.warning("跳过工艺路线节点默认数据，节点不存在: route_code=%s node_code=%s", route.code, child.get("node_code"))
                continue
            db.add(
                ProcessRouteNode(
                    route_id=route.id,
                    node_id=child_node.id,
                    sort_order=int(child.get("sort_order") or 0),
                    node_params_json=child.get("node_params_json"),
                    remark=child.get("remark"),
                    is_deleted=False,
                )
            )
        for child in row.get("calculation_outputs", []):
            child_product = product_map.get(child.get("product_code")) if child.get("product_code") else None
            db.add(
                ProcessCalculationOutput(
                    route_id=route.id,
                    output_type=child["output_type"],
                    product_id=child_product.id if child_product else None,
                    output_name=child["output_name"],
                    spec=child.get("spec"),
                    formula_type=child.get("formula_type") or "fixed",
                    recovery_rate=_seed_decimal(child.get("recovery_rate")),
                    balance_weight=_seed_decimal(child.get("balance_weight")),
                    unit=child["unit"],
                    output_ratio=_seed_decimal(child.get("output_ratio")),
                    expression=child.get("expression"),
                    scale_param=child.get("scale_param"),
                    treatment_cost=_seed_decimal(child.get("treatment_cost")),
                    sort_order=int(child.get("sort_order") or 0),
                    remark=child.get("remark"),
                    created_by=operator_id,
                    updated_by=operator_id,
                    is_deleted=False,
                )
            )

    logger.info(
        "工艺配置默认数据初始化完成: materials=%s products=%s consumables=%s public_services=%s nodes=%s routes=%s",
        len(material_map),
        len(product_map),
        len(consumable_map),
        len(service_map),
        len(node_map),
        len(data.get("routes", [])),
    )


def _seed_decimal(value: Any, default: str = "0") -> Decimal:
    return Decimal(str(default if value is None or value == "" else value))


def _seed_library_fields(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "code": row["code"],
        "name": row["name"],
        "type": row["type"],
        "description": row.get("description"),
        "unit": row["unit"],
        "status": row.get("status") or "enabled",
        "sort_order": int(row.get("sort_order") or 0),
        "remark": row.get("remark"),
    }


def _seed_process_node_children(
    db: Session,
    node: Any,
    row: dict[str, Any],
    material_map: dict[str, Any],
    product_map: dict[str, Any],
    consumable_map: dict[str, Any],
    service_map: dict[str, Any],
) -> None:
    from app.models.process_config import (
        ProcessNodeConsumable,
        ProcessNodeEquipment,
        ProcessNodeMaterialInput,
        ProcessNodeOutput,
        ProcessNodePublicService,
    )

    for child in row.get("material_inputs", []):
        material = material_map.get(child.get("material_code"))
        if material is None:
            logger.warning("跳过节点原料默认数据，原料不存在: node_code=%s material_code=%s", node.code, child.get("material_code"))
            continue
        db.add(
            ProcessNodeMaterialInput(
                node_id=node.id,
                material_id=material.id,
                amount_per_ton=_seed_decimal(child.get("amount_per_ton")),
                unit=child["unit"],
                sort_order=int(child.get("sort_order") or 0),
                remark=child.get("remark"),
                is_deleted=False,
            )
        )

    for child in row.get("consumables", []):
        consumable = consumable_map.get(child.get("consumable_code"))
        if consumable is None:
            logger.warning("跳过节点消耗品默认数据，消耗品不存在: node_code=%s consumable_code=%s", node.code, child.get("consumable_code"))
            continue
        db.add(
            ProcessNodeConsumable(
                node_id=node.id,
                consumable_id=consumable.id,
                amount_per_ton=_seed_decimal(child.get("amount_per_ton")),
                formula_type=child.get("formula_type") or "fixed",
                amount_per_ton_bm=_seed_decimal(child.get("amount_per_ton_bm")),
                expression=child.get("expression"),
                scale_param=child.get("scale_param"),
                balance_weight=_seed_decimal(child.get("balance_weight")),
                unit=child["unit"],
                sort_order=int(child.get("sort_order") or 0),
                remark=child.get("remark"),
                is_deleted=False,
            )
        )

    for child in row.get("public_services", []):
        service = service_map.get(child.get("public_service_code"))
        if service is None:
            logger.warning("跳过节点公辅默认数据，公共服务不存在: node_code=%s service_code=%s", node.code, child.get("public_service_code"))
            continue
        db.add(
            ProcessNodePublicService(
                node_id=node.id,
                public_service_id=service.id,
                amount_per_ton=_seed_decimal(child.get("amount_per_ton")),
                formula_type=child.get("formula_type") or "fixed",
                amount_per_ton_bm=_seed_decimal(child.get("amount_per_ton_bm")),
                expression=child.get("expression"),
                scale_param=child.get("scale_param"),
                balance_weight=_seed_decimal(child.get("balance_weight")),
                unit=child["unit"],
                sort_order=int(child.get("sort_order") or 0),
                remark=child.get("remark"),
                is_deleted=False,
            )
        )

    for child in row.get("equipment", []):
        db.add(
            ProcessNodeEquipment(
                node_id=node.id,
                equipment_name=child["equipment_name"],
                equipment_type=child.get("equipment_type"),
                quantity=_seed_decimal(child.get("quantity")),
                investment_amount=_seed_decimal(child.get("investment_amount")),
                currency=child.get("currency") or "CNY",
                sort_order=int(child.get("sort_order") or 0),
                remark=child.get("remark"),
                is_deleted=False,
            )
        )

    for child in row.get("outputs", []):
        product = product_map.get(child.get("product_code"))
        if product is None:
            logger.warning("跳过节点产出默认数据，产出物不存在: node_code=%s product_code=%s", node.code, child.get("product_code"))
            continue
        db.add(
            ProcessNodeOutput(
                node_id=node.id,
                product_id=product.id,
                output_type=child.get("output_type") or "product",
                output_per_ton=_seed_decimal(child.get("output_per_ton")),
                formula_type=child.get("formula_type") or "fixed",
                expression=child.get("expression"),
                scale_param=child.get("scale_param"),
                balance_weight=_seed_decimal(child.get("balance_weight")),
                treatment_cost=_seed_decimal(child.get("treatment_cost")),
                unit=child["unit"],
                is_main_product=bool(child.get("is_main_product")),
                sort_order=int(child.get("sort_order") or 0),
                remark=child.get("remark"),
                is_deleted=False,
            )
        )


def _seed_default_reranker_config(db: Session, disabled_providers: set[str]) -> None:
    """初始化默认 Reranker 配置，供试用环境首启自动预热。"""

    settings = get_settings()
    exists = db.scalar(select(ModelConfig).where(ModelConfig.model_type == "reranker", ModelConfig.is_default.is_(True)))
    if exists:
        return

    provider = str(getattr(settings, "reranker_provider", "") or "").strip()
    provider_key = provider.lower()
    model_name = str(getattr(settings, "reranker_model", "") or getattr(settings, "model_service_reranker_model", "") or "").strip()
    api_base = str(getattr(settings, "reranker_api_base", "") or "").strip() or None
    api_key = str(getattr(settings, "reranker_api_key", "") or "").strip() or None
    if provider_key in MODEL_SERVICE_PROVIDERS:
        api_base = api_base or getattr(settings, "model_service_api_base", None)
        api_key = api_key or getattr(settings, "model_service_api_key", None)

    if not provider:
        return
    if provider_key in disabled_providers:
        return
    if not model_name:
        return
    if provider_key not in LOCAL_RERANKER_PROVIDERS and not api_base:
        return

    db.add(
        ModelConfig(
            provider=provider,
            model_name=model_name,
            api_base=None if provider_key in LOCAL_RERANKER_PROVIDERS else api_base,
            api_key=None if provider_key in LOCAL_RERANKER_PROVIDERS else api_key,
            model_type="reranker",
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

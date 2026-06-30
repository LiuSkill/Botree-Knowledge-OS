"""project document management and RBAC fields

Revision ID: 20260626_project_document_rbac_fields
Revises: 20260625_three_level_security
Create Date: 2026-06-26
"""

from __future__ import annotations

from collections.abc import Callable, Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260626_project_document_rbac_fields"
down_revision: str | None = "20260625_three_level_security"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _inspector() -> sa.Inspector:
    return sa.inspect(op.get_bind())


def _dialect_name() -> str:
    return op.get_bind().dialect.name


def _has_table(table_name: str) -> bool:
    return table_name in set(_inspector().get_table_names())


def _has_column(table_name: str, column_name: str) -> bool:
    if not _has_table(table_name):
        return False
    return column_name in {column["name"] for column in _inspector().get_columns(table_name)}


def _has_index(table_name: str, index_name: str) -> bool:
    if not _has_table(table_name):
        return False
    return index_name in {index["name"] for index in _inspector().get_indexes(table_name)}


def _add_column_if_missing(table_name: str, column_factory: Callable[[], sa.Column]) -> None:
    column = column_factory()
    if not _has_table(table_name) or _has_column(table_name, column.name):
        return
    op.add_column(table_name, column)


def _create_index_if_missing(table_name: str, index_name: str, columns: list[str]) -> None:
    if _has_table(table_name) and not _has_index(table_name, index_name):
        op.create_index(index_name, table_name, columns)


def _concat_version_expr() -> str:
    return "CONCAT('v', COALESCE(version_no, 1))" if _dialect_name() == "mysql" else "'v' || COALESCE(version_no, 1)"


def _add_role_fields() -> None:
    _add_column_if_missing(
        "roles",
        lambda: sa.Column(
            "data_scope",
            sa.String(length=30),
            nullable=False,
            server_default="own",
            comment="角色项目数据范围: all/department/own/public_only",
        ),
    )
    if _has_column("roles", "data_scope"):
        op.execute(
            sa.text(
                """
                UPDATE roles
                SET data_scope = CASE
                    WHEN code = 'admin' THEN 'all'
                    WHEN code = 'engineer' THEN 'all'
                    WHEN code = 'viewer' THEN 'public_only'
                    ELSE COALESCE(NULLIF(data_scope, ''), 'own')
                END
                WHERE data_scope IS NULL OR data_scope = '' OR code IN ('admin', 'engineer', 'viewer')
                """
            )
        )
        _create_index_if_missing("roles", "idx_roles_data_scope", ["data_scope"])


def _add_project_fields() -> None:
    columns: list[Callable[[], sa.Column]] = [
        lambda: sa.Column("project_short_name", sa.String(length=100), nullable=True, comment="项目简称"),
        lambda: sa.Column("project_english_name", sa.String(length=255), nullable=True, comment="英文名称"),
        lambda: sa.Column("customer_name", sa.String(length=255), nullable=True, comment="客户名称"),
        lambda: sa.Column("project_type", sa.String(length=100), nullable=True, comment="项目类型"),
        lambda: sa.Column("project_status", sa.String(length=30), nullable=False, server_default="进行中", comment="项目状态"),
        lambda: sa.Column("project_stage", sa.String(length=100), nullable=True, comment="项目阶段"),
        lambda: sa.Column("raw_material_type", sa.String(length=255), nullable=True, comment="原料类型"),
        lambda: sa.Column("capacity", sa.String(length=255), nullable=True, comment="处理能力"),
        lambda: sa.Column("process_route", sa.Text(), nullable=True, comment="工艺路线"),
        lambda: sa.Column("main_products", sa.Text(), nullable=True, comment="主要产品"),
        lambda: sa.Column("scope_description", sa.Text(), nullable=True, comment="项目范围"),
        lambda: sa.Column("deliverables", sa.Text(), nullable=True, comment="交付成果"),
        lambda: sa.Column("owner_id", sa.Integer(), nullable=True, comment="项目负责人ID"),
        lambda: sa.Column("owner_name", sa.String(length=100), nullable=True, comment="项目负责人"),
        lambda: sa.Column("department_id", sa.Integer(), nullable=True, comment="所属部门ID"),
        lambda: sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default=sa.false(), comment="是否删除"),
        lambda: sa.Column("deleted_at", sa.DateTime(), nullable=True, comment="删除时间"),
    ]
    for column_factory in columns:
        _add_column_if_missing("projects", column_factory)
    if _has_table("projects"):
        op.execute(
            sa.text(
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
        _create_index_if_missing("projects", "idx_projects_is_deleted", ["is_deleted"])
        _create_index_if_missing("projects", "idx_projects_project_status", ["project_status"])


def _add_directory_fields() -> None:
    columns: list[Callable[[], sa.Column]] = [
        lambda: sa.Column("default_security_level", sa.String(length=30), nullable=False, server_default="internal", comment="目录默认密级"),
        lambda: sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default=sa.false(), comment="是否删除"),
        lambda: sa.Column("deleted_at", sa.DateTime(), nullable=True, comment="删除时间"),
    ]
    for column_factory in columns:
        _add_column_if_missing("knowledge_categories", column_factory)
    if _has_table("knowledge_categories"):
        op.execute(
            sa.text(
                """
                    UPDATE knowledge_categories
                    SET
                        default_security_level = COALESCE(NULLIF(default_security_level, ''), 'internal'),
                        is_deleted = COALESCE(is_deleted, 0)
                """
            )
        )
        _create_index_if_missing("knowledge_categories", "idx_knowledge_categories_deleted", ["is_deleted"])


def _add_document_fields() -> None:
    columns: list[Callable[[], sa.Column]] = [
        lambda: sa.Column("storage_path", sa.String(length=500), nullable=False, server_default="", comment="文件存储路径"),
        lambda: sa.Column("category_id", sa.Integer(), nullable=True, comment="知识分类ID"),
        lambda: sa.Column("document_status", sa.String(length=30), nullable=False, server_default="pending_review", comment="兼容文档状态"),
        lambda: sa.Column("review_status", sa.String(length=30), nullable=False, server_default="draft", comment="兼容审核状态"),
        lambda: sa.Column("index_status", sa.String(length=30), nullable=False, server_default="not_indexed", comment="索引状态"),
        lambda: sa.Column("version_no", sa.Integer(), nullable=False, server_default="1", comment="当前版本号"),
        lambda: sa.Column("current_version", sa.Boolean(), nullable=False, server_default=sa.true(), comment="兼容当前版本标识"),
        lambda: sa.Column("created_by", sa.Integer(), nullable=True, comment="创建人ID"),
        lambda: sa.Column("directory_id", sa.Integer(), nullable=True, comment="所属项目资料目录ID"),
        lambda: sa.Column("document_name", sa.String(length=255), nullable=True, comment="文件名称"),
        lambda: sa.Column("document_type", sa.String(length=50), nullable=True, comment="文档类型"),
        lambda: sa.Column("discipline", sa.String(length=50), nullable=True, comment="所属专业"),
        lambda: sa.Column("version", sa.String(length=50), nullable=True, comment="版本号"),
        lambda: sa.Column("status", sa.String(length=30), nullable=False, server_default="待审核", comment="文件状态"),
        lambda: sa.Column("upload_user_id", sa.Integer(), nullable=True, comment="上传人ID"),
        lambda: sa.Column("file_path", sa.String(length=500), nullable=True, comment="文件路径"),
        lambda: sa.Column("preview_url", sa.String(length=500), nullable=True, comment="预览地址"),
        lambda: sa.Column("is_current_version", sa.Boolean(), nullable=False, server_default=sa.true(), comment="是否当前版本"),
        lambda: sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default=sa.false(), comment="是否删除"),
        lambda: sa.Column("deleted_at", sa.DateTime(), nullable=True, comment="删除时间"),
        lambda: sa.Column("remark", sa.Text(), nullable=True, comment="备注"),
    ]
    for column_factory in columns:
        _add_column_if_missing("documents", column_factory)
    if _has_table("documents"):
        op.execute(
            sa.text(
                f"""
                UPDATE documents
                SET
                    document_name = COALESCE(NULLIF(document_name, ''), file_name),
                    directory_id = COALESCE(directory_id, category_id),
                    file_path = COALESCE(NULLIF(file_path, ''), storage_path),
                    version = COALESCE(NULLIF(version, ''), {_concat_version_expr()}),
                    status = CASE
                        WHEN review_status = 'approved' OR document_status IN ('active', 'reviewed') THEN '已发布'
                        WHEN status IN ('待审核', '已发布') THEN status
                        ELSE '待审核'
                    END,
                    upload_user_id = COALESCE(upload_user_id, created_by),
                    is_current_version = COALESCE(is_current_version, current_version, 1),
                    is_deleted = COALESCE(is_deleted, 0)
                """
            )
        )
        for index_name, column_name in (
            ("idx_documents_directory_id", "directory_id"),
            ("idx_documents_status", "status"),
            ("idx_documents_is_current_version", "is_current_version"),
            ("idx_documents_is_deleted", "is_deleted"),
        ):
            _create_index_if_missing("documents", index_name, [column_name])


def _add_document_version_fields() -> None:
    columns: list[Callable[[], sa.Column]] = [
        lambda: sa.Column("version_no", sa.Integer(), nullable=False, server_default="1", comment="版本号"),
        lambda: sa.Column("storage_path", sa.String(length=500), nullable=False, server_default="", comment="文件存储路径"),
        lambda: sa.Column("review_status", sa.String(length=30), nullable=False, server_default="draft", comment="兼容审核状态"),
        lambda: sa.Column("version_status", sa.String(length=30), nullable=False, server_default="draft", comment="兼容版本状态"),
        lambda: sa.Column("is_current", sa.Boolean(), nullable=False, server_default=sa.false(), comment="兼容当前版本标识"),
        lambda: sa.Column("created_by", sa.Integer(), nullable=True, comment="创建人ID"),
        lambda: sa.Column("change_summary", sa.Text(), nullable=True, comment="版本变更说明"),
        lambda: sa.Column("project_id", sa.Integer(), nullable=True, comment="所属项目ID"),
        lambda: sa.Column("version", sa.String(length=50), nullable=True, comment="版本号"),
        lambda: sa.Column("file_path", sa.String(length=500), nullable=True, comment="文件路径"),
        lambda: sa.Column("status", sa.String(length=30), nullable=False, server_default="待审核", comment="文件状态"),
        lambda: sa.Column("is_current_version", sa.Boolean(), nullable=False, server_default=sa.false(), comment="是否当前版本"),
        lambda: sa.Column("upload_user_id", sa.Integer(), nullable=True, comment="上传人ID"),
        lambda: sa.Column("version_note", sa.Text(), nullable=True, comment="版本备注"),
    ]
    for column_factory in columns:
        _add_column_if_missing("document_versions", column_factory)
    if _has_table("document_versions"):
        op.execute(
            sa.text(
                f"""
                UPDATE document_versions
                SET
                    project_id = COALESCE(
                        project_id,
                        (SELECT documents.project_id FROM documents WHERE documents.id = document_versions.document_id)
                    ),
                    version = COALESCE(NULLIF(version, ''), {_concat_version_expr()}),
                    file_path = COALESCE(NULLIF(file_path, ''), storage_path),
                    status = CASE
                        WHEN review_status = 'approved' OR version_status IN ('approved', 'current') THEN '已发布'
                        WHEN status IN ('待审核', '已发布') THEN status
                        ELSE '待审核'
                    END,
                    is_current_version = CASE WHEN is_current = 1 THEN 1 ELSE 0 END,
                    upload_user_id = COALESCE(upload_user_id, created_by),
                    version_note = COALESCE(version_note, change_summary)
                """
            )
        )
        for index_name, column_name in (
            ("idx_document_versions_project_id", "project_id"),
            ("idx_document_versions_status", "status"),
            ("idx_document_versions_current", "is_current_version"),
        ):
            _create_index_if_missing("document_versions", index_name, [column_name])


def _add_operation_log_fields() -> None:
    _add_column_if_missing("operation_logs", lambda: sa.Column("project_id", sa.Integer(), nullable=True, comment="项目ID"))
    _add_column_if_missing("operation_logs", lambda: sa.Column("user_agent", sa.String(length=500), nullable=True, comment="User-Agent"))
    _create_index_if_missing("operation_logs", "idx_operation_logs_project_id", ["project_id"])


def upgrade() -> None:
    _add_role_fields()
    _add_project_fields()
    _add_directory_fields()
    _add_document_fields()
    _add_document_version_fields()
    _add_operation_log_fields()


def downgrade() -> None:
    raise RuntimeError("Downgrade is not supported for project document RBAC field migration")

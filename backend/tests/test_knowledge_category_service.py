"""Knowledge category service tests."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

BASE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE_DIR))

from app.models import Base, KnowledgeCategory, Project, Role, User  # noqa: E402
from app.schemas.knowledge_category import KnowledgeCategoryCreate, KnowledgeCategoryUpdate  # noqa: E402
from app.services.knowledge_category_service import KnowledgeCategoryService  # noqa: E402


def make_session() -> Session:
    """创建独立内存数据库会话。"""

    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    return session_factory()


def make_operator() -> User:
    """创建有最高密级的分类维护操作人。"""

    user = User(id=1, username="category-admin", password_hash="x", real_name="Category Admin")
    user.roles = [Role(id=1, name="Admin", code="admin", enabled=True, security_level="confidential")]
    return user


def test_create_category_completes_english_name_from_chinese_input() -> None:
    """新增中文分类时应自动补齐英文名称。"""

    db = make_session()
    try:
        with patch(
            "app.services.knowledge_category_translation_service.LLMService.chat",
            return_value='{"translation":"Hydrometallurgy"}',
        ) as chat:
            category = KnowledgeCategoryService(db).create_category(
                KnowledgeCategoryCreate(scope_type="base", name="湿法冶金", code="base-hydrometallurgy"),
                make_operator(),
            )

        assert category.name == "湿法冶金"
        assert category.name_zh == "湿法冶金"
        assert category.name_en == "Hydrometallurgy"
        chat.assert_called_once()
    finally:
        db.close()


def test_create_category_falls_back_to_source_name_when_translation_fails() -> None:
    """翻译服务不可用时仍应允许新增分类。"""

    db = make_session()
    try:
        with patch(
            "app.services.knowledge_category_translation_service.LLMService.chat",
            side_effect=RuntimeError("model unavailable"),
        ):
            category = KnowledgeCategoryService(db).create_category(
                KnowledgeCategoryCreate(scope_type="base", name="湿法冶金", code="base-hydrometallurgy"),
                make_operator(),
            )

        assert category.name == "湿法冶金"
        assert category.name_zh == "湿法冶金"
        assert category.name_en == "湿法冶金"
    finally:
        db.close()


def test_create_category_completes_chinese_name_from_english_input() -> None:
    """新增英文分类时应自动补齐中文名称。"""

    db = make_session()
    try:
        with patch(
            "app.services.knowledge_category_translation_service.LLMService.chat",
            return_value='{"translation":"湿法冶金"}',
        ):
            category = KnowledgeCategoryService(db).create_category(
                KnowledgeCategoryCreate(scope_type="base", name="Hydrometallurgy", code="base-hydrometallurgy"),
                make_operator(),
            )

        assert category.name == "Hydrometallurgy"
        assert category.name_zh == "湿法冶金"
        assert category.name_en == "Hydrometallurgy"
    finally:
        db.close()


def test_update_category_retranslates_when_name_changes() -> None:
    """编辑分类名称后应按新名称重新补齐另一语种。"""

    db = make_session()
    try:
        category = KnowledgeCategory(
            scope_type="base",
            name="旧分类",
            name_zh="旧分类",
            name_en="Old Category",
            code="base-old",
            default_security_level="internal",
        )
        db.add(category)
        db.commit()

        with patch(
            "app.services.knowledge_category_translation_service.LLMService.chat",
            return_value='{"translation":"Solvent Extraction"}',
        ):
            updated = KnowledgeCategoryService(db).update_category(
                category.id,
                KnowledgeCategoryUpdate(name="萃取工艺"),
                make_operator(),
            )

        assert updated.name == "萃取工艺"
        assert updated.name_zh == "萃取工艺"
        assert updated.name_en == "Solvent Extraction"
    finally:
        db.close()


def test_list_tree_includes_i18n_names() -> None:
    """分类树响应应包含双语字段，供前端按当前语言展示。"""

    db = make_session()
    try:
        db.add(
            KnowledgeCategory(
                scope_type="base",
                name="湿法冶金",
                name_zh="湿法冶金",
                name_en="Hydrometallurgy",
                code="base-hydrometallurgy",
                default_security_level="internal",
            )
        )
        db.commit()

        tree = KnowledgeCategoryService(db).list_tree(make_operator(), "base")

        assert tree[0]["name_zh"] == "湿法冶金"
        assert tree[0]["name_en"] == "Hydrometallurgy"
        assert db.scalar(select(KnowledgeCategory.name_en)) == "Hydrometallurgy"
    finally:
        db.close()


def test_list_tree_repairs_legacy_missing_or_invalid_english_names() -> None:
    """历史分类缺少有效英文名时，加载分类树应自动补译，避免英文界面显示中文。"""

    db = make_session()
    try:
        db.add_all(
            [
                KnowledgeCategory(
                    scope_type="base",
                    name="湿法冶金",
                    name_zh="湿法冶金",
                    name_en=None,
                    code="base-hydrometallurgy",
                    sort_order=1,
                    default_security_level="internal",
                ),
                KnowledgeCategory(
                    scope_type="base",
                    name="专业手册",
                    name_zh="专业手册",
                    name_en="专业手册",
                    code="base-professional-manuals",
                    sort_order=2,
                    default_security_level="internal",
                ),
            ]
        )
        db.commit()

        with patch(
            "app.services.knowledge_category_translation_service.LLMService.chat",
            side_effect=[
                '{"translation":"Hydrometallurgy"}',
                '{"translation":"Professional Manuals"}',
            ],
        ) as chat:
            tree = KnowledgeCategoryService(db).list_tree(make_operator(), "base")

        by_code = {item["code"]: item for item in tree}
        assert by_code["base-hydrometallurgy"]["name_en"] == "Hydrometallurgy"
        assert by_code["base-professional-manuals"]["name_en"] == "Professional Manuals"
        assert chat.call_count == 2
    finally:
        db.close()


def test_list_tree_does_not_repair_builtin_categories() -> None:
    """内置分类已有前端语言包，不应在加载分类树时触发模型翻译。"""

    db = make_session()
    try:
        db.add(
            KnowledgeCategory(
                scope_type="base",
                name="工艺技术",
                name_zh="工艺技术",
                name_en=None,
                code="base-process",
                default_security_level="internal",
            )
        )
        db.commit()

        with patch("app.services.knowledge_category_translation_service.LLMService.chat") as chat:
            tree = KnowledgeCategoryService(db).list_tree(make_operator(), "base")

        assert tree[0]["name_en"] is None
        chat.assert_not_called()
    finally:
        db.close()


def test_list_tree_repairs_custom_project_directory_even_when_code_matches_template_child() -> None:
    """自定义项目目录即使编码像模板子目录，也应按动态分类补译。"""

    db = make_session()
    try:
        db.add(Project(id=1, name="测试项目", code="TEST-PROJECT", security_level="internal", created_by=1))
        db.add(
            KnowledgeCategory(
                scope_type="project",
                project_id=1,
                name="湿法冶金",
                name_zh="湿法冶金",
                name_en=None,
                code="01",
                default_security_level="internal",
            )
        )
        db.commit()

        with patch(
            "app.services.knowledge_category_translation_service.LLMService.chat",
            return_value='{"translation":"Hydrometallurgy"}',
        ) as chat:
            tree = KnowledgeCategoryService(db).list_tree(make_operator(), "project", project_id=1)

        assert tree[0]["name_en"] == "Hydrometallurgy"
        chat.assert_called_once()
    finally:
        db.close()

"""
Botree MVP Smoke Test

负责：
1. 使用独立 SQLite 数据库验证主业务闭环
2. 覆盖登录、项目、上传、审核、解析、索引和 AI 问答
3. 校验未审核资料不会被问答引用
"""

import logging
import os
import secrets
import shutil
import sys
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import select

BASE_DIR = Path(__file__).resolve().parents[1]
SMOKE_DB = BASE_DIR / "botree_knowledge_smoke.db"
SMOKE_UPLOAD_DIR = BASE_DIR / "storage" / "smoke_uploads"
SMOKE_ADMIN_PASSWORD = secrets.token_urlsafe(24)

# 测试必须在导入 FastAPI 应用前设置环境变量，确保不连接真实 MySQL。
sys.path.insert(0, str(BASE_DIR))
os.environ["DATABASE_URL"] = f"sqlite:///{SMOKE_DB.as_posix()}"
os.environ["UPLOAD_DIR"] = str(SMOKE_UPLOAD_DIR)
os.environ["JWT_SECRET_KEY"] = secrets.token_urlsafe(32)
os.environ["DEFAULT_ADMIN_PASSWORD"] = SMOKE_ADMIN_PASSWORD
os.environ["MILVUS_HOST"] = ""
os.environ["MINIO_ENDPOINT"] = ""
os.environ["MINIO_ACCESS_KEY"] = ""
os.environ["MINIO_SECRET_KEY"] = ""
os.environ["MINIO_BUCKET"] = ""
os.environ["REDIS_HOST"] = ""
os.environ["MINERU_BASE_URL"] = ""

from main import app  # noqa: E402  pylint: disable=wrong-import-position
from app.core.database import SessionLocal  # noqa: E402  pylint: disable=wrong-import-position
from app.models.chat import ChatCitation  # noqa: E402  pylint: disable=wrong-import-position
from app.models.document import Document, DocumentChunk, DocumentVersion  # noqa: E402  pylint: disable=wrong-import-position
from app.models.graph import GraphEntity, GraphRelation  # noqa: E402  pylint: disable=wrong-import-position
from app.models.index_task import IndexTask  # noqa: E402  pylint: disable=wrong-import-position
from app.models.page_index import DocumentPage, DocumentPageBlock, PageIndex  # noqa: E402  pylint: disable=wrong-import-position
from app.models.retrieval_trace import RetrievalTrace  # noqa: E402  pylint: disable=wrong-import-position
from app.models.review import ReviewLog, ReviewTask  # noqa: E402  pylint: disable=wrong-import-position

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s [%(name)s] %(message)s")


def reset_runtime_state() -> None:
    """
    重置烟测运行状态

    说明：
        仅删除 backend 目录下的 smoke 专用数据库和上传目录，不影响真实开发数据。
    """

    if SMOKE_DB.exists():
        SMOKE_DB.unlink()
    if SMOKE_UPLOAD_DIR.exists():
        shutil.rmtree(SMOKE_UPLOAD_DIR)


def assert_ok(response, message: str) -> dict:
    """
    校验统一 API 响应

    参数:
        response: TestClient 返回对象
        message: 断言失败时的上下文说明

    返回:
        后端统一响应中的 data 字段。
    """

    assert response.status_code == 200, f"{message}: HTTP {response.status_code} {response.text}"
    payload = response.json()
    assert payload["code"] == 0, f"{message}: {payload}"
    return payload["data"]


def main() -> None:
    """
    执行 MVP 主流程烟测

    流程：
        登录 -> 创建项目 -> 上传资料 -> 未审核问答 -> 提交审核 -> 审核通过
        -> 解析 -> 索引 -> AI 问答 -> 校验引用来源和审计记录。
    """

    reset_runtime_state()
    with TestClient(app) as client:
        logger.info("开始执行 Botree MVP 烟测")

        login = assert_ok(
            client.post("/api/auth/login", json={"username": "admin", "password": SMOKE_ADMIN_PASSWORD}),
            "管理员登录",
        )
        token = login["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        project = assert_ok(
            client.post(
                "/api/projects",
                json={
                    "name": "烟测项目",
                    "code": "SMOKE-PROJECT",
                    "client": "Botree",
                    "manager": "系统管理员",
                    "description": "用于验证 MVP 主流程的项目",
                },
                headers=headers,
            ),
            "创建项目",
        )
        knowledge_base_id = project["knowledge_base_id"]
        categories = assert_ok(
            client.get(f"/api/knowledge-categories?scope_type=project&project_id={project['id']}", headers=headers),
            "查询项目知识分类",
        )
        assert categories, "项目创建后必须初始化默认知识分类"
        category_id = categories[0]["id"]

        base_bases = assert_ok(client.get("/api/knowledge-bases?type=base", headers=headers), "query base knowledge bases")
        assert base_bases, "default base knowledge base must exist"
        base_knowledge_base_id = base_bases[0]["id"]
        base_categories = assert_ok(
            client.get("/api/knowledge-categories?scope_type=base", headers=headers),
            "query base knowledge categories",
        )
        assert base_categories, "default base knowledge categories must exist"
        base_category_id = base_categories[0]["id"]

        document_content = (
            "Botree 烟测资料\n"
            "本项目采用项目知识隔离策略，资料通过审核并完成索引后，AI 才能引用该资料回答。\n"
            "关键设备编号为 E-1001，设计压力为 1.6MPa。"
        ).encode("utf-8")
        document = assert_ok(
            client.post(
                f"/api/knowledge-bases/{knowledge_base_id}/documents/upload",
                files={"file": ("smoke.md", document_content, "text/markdown")},
                data={"category_id": str(category_id)},
                headers=headers,
            ),
            "上传项目资料",
        )

        no_project_response = client.post(
            "/api/chat/completions",
            json={"chat_type": "project_chat", "message": "未选择项目时不允许提问", "agent_enabled": True},
            headers=headers,
        )
        assert no_project_response.status_code == 400, "项目问答未选择项目时必须拒绝"

        before_answer = assert_ok(
            client.post(
                "/api/chat/completions",
                json={
                    "chat_type": "project_chat",
                    "project_id": project["id"],
                    "message": "E-1001 的设计压力是多少？",
                    "agent_enabled": True,
                },
                headers=headers,
            ),
            "未审核资料问答",
        )
        assert before_answer["citations"] == [], "未审核资料不应产生引用"
        assert "当前知识库未找到足够依据" in before_answer["answer"], "无依据回答必须明确说明"

        review = assert_ok(
            client.post(f"/api/documents/{document['id']}/submit-review", json={"comment": "提交烟测审核"}, headers=headers),
            "提交审核",
        )
        assert_ok(
            client.post(f"/api/review-tasks/{review['review_task_id']}/approve", json={"comment": "烟测通过"}, headers=headers),
            "审核通过",
        )
        parse_result = assert_ok(client.post(f"/api/documents/{document['id']}/parse", headers=headers), "解析文档")
        assert parse_result["chunk_count"] >= 1, "解析后应生成至少一个 Chunk"
        assert_ok(
            client.post(f"/api/documents/{document['id']}/quality-check", json={"passed": True, "comment": "烟测确认"}, headers=headers),
            "解析质量确认",
        )
        assert_ok(client.post(f"/api/documents/{document['id']}/index", headers=headers), "构建索引")

        after_answer = assert_ok(
            client.post(
                "/api/chat/completions",
                json={
                    "chat_type": "project_chat",
                    "project_id": project["id"],
                    "message": "E-1001 的设计压力是多少？",
                    "agent_enabled": True,
                },
                headers=headers,
            ),
            "索引后问答",
        )
        assert after_answer["citations"], "审核并索引后应返回引用来源"
        assert after_answer["citations"][0]["document_id"] == document["id"], "引用来源必须追溯到上传文档"

        base_answer = assert_ok(
            client.post(
                "/api/chat/completions",
                json={"chat_type": "base_chat", "message": "E-1001 的设计压力是多少？", "agent_enabled": True},
                headers=headers,
            ),
            "基础问答",
        )
        assert base_answer["chat_type"] == "base_chat", "基础问答响应必须返回 base_chat"
        assert base_answer["citations"] == [], "base chat must not cite project documents"

        base_document_content = (
            "Botree base smoke document\n"
            "Base knowledge article B-2001 says the shared design temperature is 80C.\n"
        ).encode("utf-8")
        base_document = assert_ok(
            client.post(
                f"/api/knowledge-bases/{base_knowledge_base_id}/documents/upload",
                files={"file": ("base-smoke.md", base_document_content, "text/markdown")},
                data={"category_id": str(base_category_id)},
                headers=headers,
            ),
            "upload base document",
        )
        base_review = assert_ok(
            client.post(f"/api/documents/{base_document['id']}/submit-review", json={"comment": "submit base smoke review"}, headers=headers),
            "submit base document review",
        )
        assert_ok(
            client.post(f"/api/review-tasks/{base_review['review_task_id']}/approve", json={"comment": "approve base smoke"}, headers=headers),
            "approve base document",
        )
        base_parse = assert_ok(client.post(f"/api/documents/{base_document['id']}/parse", headers=headers), "parse base document")
        assert base_parse["chunk_count"] >= 1, "base document parse must create chunks"
        assert_ok(
            client.post(
                f"/api/documents/{base_document['id']}/quality-check",
                json={"passed": True, "comment": "base smoke quality ok"},
                headers=headers,
            ),
            "confirm base parse quality",
        )
        assert_ok(client.post(f"/api/documents/{base_document['id']}/index", headers=headers), "index base document")

        base_indexed_answer = assert_ok(
            client.post(
                "/api/chat/completions",
                json={"chat_type": "base_chat", "message": "What is the shared design temperature in B-2001?", "agent_enabled": True},
                headers=headers,
            ),
            "base indexed chat",
        )
        assert base_indexed_answer["citations"], "base chat must cite indexed base documents"
        assert base_indexed_answer["citations"][0]["document_id"] == base_document["id"], "base citation must trace to base document"

        project_base_answer = assert_ok(
            client.post(
                "/api/chat/completions",
                json={
                    "chat_type": "project_chat",
                    "project_id": project["id"],
                    "message": "What is the shared design temperature in B-2001?",
                    "agent_enabled": True,
                },
                headers=headers,
            ),
            "project chat must not cite base document",
        )
        assert project_base_answer["citations"] == [], "project chat must not cite base knowledge documents"

        audits = assert_ok(client.get("/api/system/qa-audits", headers=headers), "问答审计")
        assert len(audits) >= 4, "问答审计应记录问答历史"

        with SessionLocal() as db:
            citation_message_ids = list(
                db.scalars(
                    select(ChatCitation.message_id).where(ChatCitation.document_id == document["id"]).distinct().order_by(ChatCitation.message_id)
                ).all()
            )
            assert citation_message_ids, "删除前必须存在引用消息，才能验证检索清理链路"

        delete_result = assert_ok(client.delete(f"/api/documents/{document['id']}", headers=headers), "删除文档")
        assert delete_result["deleted"] is True, "删除接口必须明确返回删除成功"
        assert delete_result["document_chunks"] >= 1, "删除结果必须包含 Chunk 清理数量"
        assert delete_result["document_versions"] >= 1, "删除结果必须包含版本清理数量"
        assert delete_result["chat_citations"] >= 1, "删除结果必须包含引用清理数量"
        assert delete_result["retrieval_traces"] >= 1, "删除结果必须包含检索审计清理数量"

        deleted_document_response = client.get(f"/api/documents/{document['id']}", headers=headers)
        assert deleted_document_response.status_code == 404, "文档删除后再次查询详情必须返回 404"

        with SessionLocal() as db:
            assert db.scalar(select(Document).where(Document.id == document["id"])) is None, "文档主表记录必须被删除"
            assert not list(db.scalars(select(DocumentVersion).where(DocumentVersion.document_id == document["id"])).all()), "文档版本必须被删除"
            assert not list(db.scalars(select(DocumentChunk).where(DocumentChunk.document_id == document["id"])).all()), "文档 Chunk 必须被删除"
            assert not list(db.scalars(select(DocumentPage).where(DocumentPage.document_id == document["id"])).all()), "文档页必须被删除"
            assert not list(
                db.scalars(select(DocumentPageBlock).where(DocumentPageBlock.document_id == document["id"])).all()
            ), "文档页块必须被删除"
            assert not list(db.scalars(select(PageIndex).where(PageIndex.document_id == document["id"])).all()), "PageIndex 必须被删除"
            assert not list(db.scalars(select(GraphEntity).where(GraphEntity.document_id == document["id"])).all()), "图谱实体必须被删除"
            assert not list(
                db.scalars(select(GraphRelation).where(GraphRelation.document_id == document["id"])).all()
            ), "图谱关系必须被删除"
            assert not list(db.scalars(select(ReviewTask).where(ReviewTask.document_id == document["id"])).all()), "审核任务必须被删除"
            assert not list(db.scalars(select(ReviewLog).where(ReviewLog.document_id == document["id"])).all()), "审核日志必须被删除"
            assert not list(db.scalars(select(IndexTask).where(IndexTask.document_id == document["id"])).all()), "索引任务必须被删除"
            assert not list(
                db.scalars(select(ChatCitation).where(ChatCitation.document_id == document["id"])).all()
            ), "聊天引用必须被删除"
            assert not list(
                db.scalars(select(RetrievalTrace).where(RetrievalTrace.message_id.in_(citation_message_ids))).all()
            ), "检索审计必须随文档引用一起删除"

        logger.info("Botree MVP 烟测通过")


if __name__ == "__main__":
    main()

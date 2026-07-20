"""
Botree Knowledge OS FastAPI Application

负责：
1. 创建 FastAPI 应用
2. 注册 API 路由、CORS 和异常处理器
3. 启动时初始化数据库和默认数据
"""

import logging
import sys

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from app.api import auth, chat, departments, documents, knowledge_bases, knowledge_categories, model_configs, process_config, projects, retrieval, reviews, roles, sensitive_content, system, users
from app.core.audit_context import RequestAuditContext, reset_request_audit_context, set_request_audit_context
from app.core.config import get_settings
from app.core.database import SessionLocal, init_database
from app.core.exceptions import AppException, register_exception_handlers
from app.services.embedding_service import EmbeddingService
from app.services.reranker_service import RerankerService

def configure_logging() -> None:
    """
    配置应用日志。

    职责：
    - 统一日志格式，便于排查接口、检索和模型调用问题
    - 在 Windows 控制台下强制使用 UTF-8，避免中文日志出现乱码
    """

    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8", errors="replace")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s [%(name)s] %(message)s")


configure_logging()
logger = logging.getLogger(__name__)

settings = get_settings()

app = FastAPI(
    title=settings.app_name,
    description="Botree Agent / Botree Knowledge OS 企业知识管理与智能体应用平台 MVP",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_allow_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _request_ip(request: Request) -> str | None:
    forwarded_for = request.headers.get("x-forwarded-for")
    if forwarded_for:
        return forwarded_for.split(",", 1)[0].strip()
    return request.client.host if request.client else None


@app.middleware("http")
async def audit_context_middleware(request: Request, call_next):
    token = set_request_audit_context(
        RequestAuditContext(
            ip_address=_request_ip(request),
            user_agent=request.headers.get("user-agent"),
            method=request.method,
            path=request.url.path,
        )
    )
    try:
        return await call_next(request)
    finally:
        reset_request_audit_context(token)

register_exception_handlers(app)

app.include_router(auth.router, prefix=settings.api_prefix)
app.include_router(users.router, prefix=settings.api_prefix)
app.include_router(users.current_user_router, prefix=settings.api_prefix)
app.include_router(roles.router, prefix=settings.api_prefix)
app.include_router(sensitive_content.router, prefix=settings.api_prefix)
app.include_router(projects.router, prefix=settings.api_prefix)
app.include_router(knowledge_bases.router, prefix=settings.api_prefix)
app.include_router(knowledge_categories.router, prefix=settings.api_prefix)
app.include_router(documents.router, prefix=settings.api_prefix)
app.include_router(reviews.router, prefix=settings.api_prefix)
app.include_router(reviews.document_review_router, prefix=settings.api_prefix)
app.include_router(retrieval.router, prefix=settings.api_prefix)
app.include_router(chat.router, prefix=settings.api_prefix)
app.include_router(model_configs.router, prefix=settings.api_prefix)
app.include_router(process_config.router, prefix=settings.api_prefix)
app.include_router(system.router, prefix=settings.api_prefix)
app.include_router(departments.router, prefix=settings.api_prefix)
app.include_router(system.health_router, prefix=settings.api_prefix)


def warmup_embedding_model() -> None:
    """
    预热本地 Embedding 模型。

    说明:
        预热只复用现有 EmbeddingService 配置解析，不改变对外 API 调用方式。
        预热失败不阻断应用启动，实际业务调用仍按原有异常链路返回标准错误。
    """

    try:
        with SessionLocal() as db:
            EmbeddingService(db).warmup_local_embedding()
    except AppException as exc:
        logger.warning("本地Embedding预热失败，服务继续启动: error=%s", exc.message)
    except Exception as exc:
        logger.exception("本地Embedding预热出现未预期异常，服务继续启动: error=%s", exc)


def warmup_reranker_model() -> None:
    """
    预热本地 Reranker 模型。

    说明：启动时加载默认启用的本地 reranker 到进程缓存，避免首轮问答承担模型加载耗时。
    """

    try:
        with SessionLocal() as db:
            RerankerService(db).warmup_local_reranker()
    except AppException as exc:
        logger.warning("本地Reranker预热失败，服务继续启动: error=%s", exc.message)
    except Exception as exc:
        logger.exception("本地Reranker预热出现未预期异常，服务继续启动: error=%s", exc)


@app.on_event("startup")
def on_startup() -> None:
    """
    应用启动事件

    负责：
    - 初始化数据库表
    - 创建默认管理员和基础数据
    """

    init_database()
    warmup_embedding_model()
    warmup_reranker_model()
    logger.info("Botree Knowledge OS 后端启动完成")

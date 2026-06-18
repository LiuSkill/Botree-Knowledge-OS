"""
Review Service

负责：
1. 文档提交审核
2. 审核通过和驳回
3. 记录审核日志，保障入库流程可追溯
"""

import logging

from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.core.exceptions import AppException, is_database_lock_error
from app.models.document import Document, DocumentVersion
from app.models.review import ReviewLog, ReviewTask
from app.models.user import User
from app.repositories.document_repository import DocumentRepository
from app.repositories.review_repository import ReviewRepository
from app.repositories.user_repository import UserRepository
from app.services.document_service import DocumentService
from app.services.knowledge_category_service import KnowledgeCategoryService
from app.services.system_service import SystemService
from app.utils.time_utils import now_utc

logger = logging.getLogger(__name__)

REVIEW_STATUS_DRAFT = "draft"
REVIEW_STATUS_REJECTED = "rejected"
REVIEW_STATUS_REVIEWING = "reviewing"
REVIEW_STATUS_SUBMITTED = "submitted"
VERSION_STATUS_PENDING_REVIEW = "pending_review"
SUBMITTABLE_REVIEW_STATUSES = {REVIEW_STATUS_DRAFT, REVIEW_STATUS_REJECTED}


class ReviewService:
    """
    审核服务

    职责：
    - 执行提交审核、通过、驳回
    - 确保未审核资料不能进入解析和问答
    """

    def __init__(self, db: Session) -> None:
        self.db = db
        self.repository = ReviewRepository(db)
        self.document_repository = DocumentRepository(db)
        self.category_service = KnowledgeCategoryService(db)
        self.user_repository = UserRepository(db)

    def _resolve_submit_version(self, document: Document, version_no: int | None = None) -> DocumentVersion | None:
        """
        定位本次提交审核的版本。

        明确传入版本号时严格提交该版本；未传版本号时，优先选择最新的草稿/驳回版本，
        便于列表页一键送审，同时兼容历史数据中只有文档主表、没有版本记录的情况。
        """

        if version_no is not None:
            return self.document_repository.get_version(document.id, version_no)
        for version in self.document_repository.list_versions(document.id):
            if version.review_status in SUBMITTABLE_REVIEW_STATUSES:
                return version
        return self.document_repository.get_current_version(document.id) or self.document_repository.get_version(document.id, document.version_no)

    def submit_review(self, document_id: int, operator: User, comment: str | None = None, version_no: int | None = None) -> ReviewTask:
        """提交文档或指定版本审核。"""

        try:
            document = DocumentService(self.db).get_document(document_id, operator)
            version = self._resolve_submit_version(document, version_no)
            if version is None:
                if document.review_status not in SUBMITTABLE_REVIEW_STATUSES:
                    raise AppException("当前状态不允许提交审核")
            elif version.review_status not in SUBMITTABLE_REVIEW_STATUSES:
                raise AppException("当前版本状态不允许提交审核")

            submitted_at = now_utc()
            current_version = self.document_repository.get_current_version(document.id)
            if version is not None:
                version.review_status = REVIEW_STATUS_REVIEWING
                version.version_status = VERSION_STATUS_PENDING_REVIEW
                version.review_comment = comment

            if version is None or current_version is None or current_version.id == version.id:
                document.review_status = REVIEW_STATUS_SUBMITTED
                document.submitted_by = operator.id
                document.submitted_at = submitted_at
                document.review_comment = comment

            task = self.repository.get_open_task_by_document(document.id, version.id if version else None)
            if not task:
                task = self.repository.add_task(
                    ReviewTask(
                        document_id=document.id,
                        version_id=version.id if version else None,
                        version_no=version.version_no if version else document.version_no,
                        review_status=REVIEW_STATUS_REVIEWING,
                        review_comment=comment,
                    )
                )
            else:
                task.review_comment = comment
            self.repository.add_log(
                ReviewLog(
                    document_id=document.id,
                    version_id=version.id if version else None,
                    version_no=version.version_no if version else document.version_no,
                    action="submit",
                    operator_id=operator.id,
                    comment=comment,
                )
            )
            SystemService(self.db).record_operation(operator, "提交审核", "document", document.id, comment or "提交文档审核")
            self.db.commit()
            logger.info(
                "文档提交审核: document_id=%s version_id=%s version_no=%s project_id=%s file_name=%s operation=%s status=%s error_message=%s timestamp=%s",
                document.id,
                version.id if version else None,
                version.version_no if version else document.version_no,
                document.project_id,
                version.file_name if version else document.file_name,
                "submit_review",
                "success",
                None,
                submitted_at.isoformat(),
            )
            return task
        except OperationalError as exc:
            self.db.rollback()
            if is_database_lock_error(exc):
                logger.warning(
                    "文档提交审核锁等待失败: document_id=%s version_no=%s operator_id=%s operation=%s status=%s",
                    document_id,
                    version_no,
                    operator.id,
                    "submit_review",
                    "lock_wait_timeout",
                )
                raise AppException("当前文档正在被其他任务处理，请稍后重试", status_code=409, code=409) from exc
            raise

    def list_tasks(self, status: str | None = None) -> list[ReviewTask]:
        """查询审核任务。"""

        tasks = self.repository.list_tasks(status)
        self._attach_task_display_fields(tasks)
        return tasks

    def get_task(self, task_id: int) -> ReviewTask:
        """查询审核任务详情。"""

        task = self.repository.get_task(task_id)
        if not task:
            raise AppException("审核任务不存在", status_code=404, code=404)
        self._attach_task_display_fields([task])
        return task

    def _attach_task_display_fields(self, tasks: list[ReviewTask]) -> None:
        """
        补齐审核任务列表展示字段。

        审核任务本身只保存流程状态，列表展示需要结合文档、版本、分类和上传人信息。
        这些字段仅用于接口序列化，不回写审核任务表。
        """

        for task in tasks:
            document = self.document_repository.get(task.document_id)
            version = self.document_repository.get_version_by_id(task.version_id) if task.version_id else None
            if version is None and task.version_no:
                version = self.document_repository.get_version(task.document_id, task.version_no)

            category_id = version.category_id if version and version.category_id is not None else document.category_id if document else None
            uploader_id = version.created_by if version and version.created_by is not None else document.created_by if document else None
            uploader = self.user_repository.get_by_id(uploader_id) if uploader_id is not None else None

            setattr(task, "document_file_name", version.file_name if version else document.file_name if document else None)
            setattr(task, "document_category_name", self.category_service.category_name(category_id))
            setattr(task, "document_category_path", self.category_service.category_path(category_id))
            setattr(task, "display_version_no", task.version_no or (version.version_no if version else document.version_no if document else None))
            setattr(task, "uploader_id", uploader_id)
            setattr(task, "uploader_name", uploader.real_name if uploader else None)
            setattr(task, "uploader_username", uploader.username if uploader else None)

    def approve(self, task_id: int, operator: User, comment: str | None = None) -> ReviewTask:
        """审核通过。"""

        task = self.get_task(task_id)
        document = DocumentService(self.db).get_document(task.document_id, operator)
        if task.review_status != "reviewing":
            raise AppException("审核任务已处理")
        version = self.document_repository.get_version_by_id(task.version_id) if task.version_id else None
        if version is None:
            version = self.document_repository.get_version(task.document_id, task.version_no or document.version_no)
        if version is None:
            raise AppException("审核任务关联的版本不存在", status_code=404, code=404)
        task.review_status = "approved"
        task.reviewer_id = operator.id
        task.review_comment = comment
        task.reviewed_at = now_utc()
        version.review_status = "approved"
        version.version_status = "approved"
        version.reviewed_by = operator.id
        version.reviewed_at = task.reviewed_at
        version.review_comment = comment
        if not self.document_repository.get_current_version(document.id) or document.version_no == version.version_no:
            document.review_status = "approved"
            document.document_status = "reviewed"
            document.reviewed_by = operator.id
            document.reviewed_at = task.reviewed_at
            document.review_comment = comment
        self.repository.add_log(
            ReviewLog(
                document_id=document.id,
                version_id=version.id,
                version_no=version.version_no,
                action="approve",
                operator_id=operator.id,
                comment=comment,
            )
        )
        SystemService(self.db).record_operation(operator, "审核通过", "document", document.id, comment or "审核通过")
        self.db.commit()
        self._attach_task_display_fields([task])
        logger.info(
            "审核通过: document_id=%s version_id=%s version_no=%s project_id=%s file_name=%s operation=%s status=%s error_message=%s timestamp=%s",
            document.id,
            version.id,
            version.version_no,
            document.project_id,
            version.file_name,
            "review_approve",
            "success",
            None,
            task.reviewed_at.isoformat(),
        )
        return task

    def reject(self, task_id: int, operator: User, comment: str | None = None) -> ReviewTask:
        """审核驳回。"""

        task = self.get_task(task_id)
        document = DocumentService(self.db).get_document(task.document_id, operator)
        if task.review_status != "reviewing":
            raise AppException("审核任务已处理")
        version = self.document_repository.get_version_by_id(task.version_id) if task.version_id else None
        if version is None:
            version = self.document_repository.get_version(task.document_id, task.version_no or document.version_no)
        if version is None:
            raise AppException("审核任务关联的版本不存在", status_code=404, code=404)
        task.review_status = "rejected"
        task.reviewer_id = operator.id
        task.review_comment = comment
        task.reviewed_at = now_utc()
        version.review_status = "rejected"
        version.version_status = "rejected"
        version.reviewed_by = operator.id
        version.reviewed_at = task.reviewed_at
        version.review_comment = comment
        if not self.document_repository.get_current_version(document.id) or document.version_no == version.version_no:
            document.review_status = "rejected"
            document.document_status = "pending_review"
            document.reviewed_by = operator.id
            document.reviewed_at = task.reviewed_at
            document.review_comment = comment
        self.repository.add_log(
            ReviewLog(
                document_id=document.id,
                version_id=version.id,
                version_no=version.version_no,
                action="reject",
                operator_id=operator.id,
                comment=comment,
            )
        )
        SystemService(self.db).record_operation(operator, "审核驳回", "document", document.id, comment or "审核驳回")
        self.db.commit()
        self._attach_task_display_fields([task])
        logger.info(
            "审核驳回: document_id=%s version_id=%s version_no=%s project_id=%s file_name=%s operation=%s status=%s error_message=%s timestamp=%s",
            document.id,
            version.id,
            version.version_no,
            document.project_id,
            version.file_name,
            "review_reject",
            "success",
            None,
            task.reviewed_at.isoformat(),
        )
        return task

    def list_logs(self, document_id: int, operator: User) -> list[ReviewLog]:
        """查询文档审核日志。"""

        DocumentService(self.db).get_document(document_id, operator)
        return self.repository.list_logs(document_id)

    def list_approved_documents(
        self,
        operator: User,
        scope_type: str | None = None,
        project_id: int | None = None,
        category_id: int | None = None,
        index_status: str | None = None,
        keyword: str | None = None,
    ) -> list:
        """
        查询审核通过资料

        参数:
            operator: 当前用户
            scope_type: 资料范围，base/project
            project_id: 项目ID
            category_id: 分类ID，包含子分类过滤
            index_status: 构建状态
            keyword: 文档名称关键字

        返回:
            已审核通过的文档列表。
        """

        if scope_type not in {None, "base", "project"}:
            raise AppException("资料范围必须为 base 或 project")
        return DocumentService(self.db).list_documents(
            operator,
            project_id=project_id,
            review_status="approved",
            category_id=category_id,
            index_status=index_status,
            knowledge_type=scope_type,
            keyword=keyword,
        )

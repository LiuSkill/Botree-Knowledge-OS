"""Projects API."""

from fastapi import APIRouter, Depends, File, Form, UploadFile
from sqlalchemy.orm import Session

from app.api.deps import require_any_permission, require_permission
from app.core.database import get_db
from app.core.exceptions import AppException
from app.core.response import success
from app.models.user import User
from app.schemas.chat import ChatCompletionRequest
from app.schemas.document import (
    DocumentDeleteOut,
    DocumentMetadataUpdate,
    DocumentOut,
    DocumentSecurityLevelUpdate,
    DocumentVersionOut,
    IndexTaskOut,
)
from app.schemas.knowledge_category import KnowledgeCategoryCreate, KnowledgeCategoryOut, KnowledgeCategoryUpdate
from app.schemas.project import ProjectCreate, ProjectMemberCreate, ProjectMemberOut, ProjectUpdate
from app.services.chat_service import ChatService
from app.services.document_service import DocumentService
from app.services.knowledge_category_service import KnowledgeCategoryService
from app.services.knowledge_base_service import KnowledgeBaseService
from app.services.project_service import ProjectService

router = APIRouter(prefix="/projects", tags=["项目中心"])


@router.get("", summary="项目列表")
def list_projects(
    keyword: str | None = None,
    project_status: str | None = None,
    security_level: str | None = None,
    current_user: User = Depends(require_any_permission("project:view", "project:chat")),
    db: Session = Depends(get_db),
) -> dict:
    """查询当前用户可访问项目。"""

    return success(ProjectService(db).list_projects(current_user, keyword, project_status, security_level))


@router.post("", summary="创建项目")
def create_project(
    payload: ProjectCreate,
    current_user: User = Depends(require_permission("project:create")),
    db: Session = Depends(get_db),
) -> dict:
    """创建项目。"""

    return success(ProjectService(db).create_project(payload, current_user))


@router.get("/{project_id}", summary="项目详情")
def get_project(
    project_id: int,
    current_user: User = Depends(require_permission("project:view")),
    db: Session = Depends(get_db),
) -> dict:
    """查询项目详情。"""

    return success(ProjectService(db).get_project(project_id, current_user))


@router.put("/{project_id}", summary="编辑项目")
def update_project(
    project_id: int,
    payload: ProjectUpdate,
    current_user: User = Depends(require_permission("project:edit")),
    db: Session = Depends(get_db),
) -> dict:
    """编辑项目。"""

    return success(ProjectService(db).update_project(project_id, payload, current_user))


@router.delete("/{project_id}", summary="删除项目")
def delete_project(
    project_id: int,
    current_user: User = Depends(require_permission("project:delete")),
    db: Session = Depends(get_db),
) -> dict:
    """软删除项目。"""

    ProjectService(db).delete_project(project_id, current_user)
    return success({"deleted": True})


@router.get("/{project_id}/directories", summary="项目资料目录")
def list_project_directories(
    project_id: int,
    keyword: str | None = None,
    status: str | None = None,
    security_level: str | None = None,
    parse_status: str | None = None,
    index_status: str | None = None,
    current_user: User = Depends(
        require_any_permission(
            "project:view",
        )
    ),
    db: Session = Depends(get_db),
) -> dict:
    """查询项目资料目录树。"""

    tree = KnowledgeCategoryService(db).list_tree(
        current_user,
        "project",
        project_id,
        keyword=keyword,
        document_status=status,
        security_level=security_level,
        parse_status=parse_status,
        index_status=index_status,
    )
    return success([KnowledgeCategoryOut.model_validate(item).model_dump(mode="json") for item in tree])


@router.post("/{project_id}/directories", summary="新建项目资料目录")
def create_project_directory(
    project_id: int,
    payload: KnowledgeCategoryCreate,
    current_user: User = Depends(require_permission("project:directory:create")),
    db: Session = Depends(get_db),
) -> dict:
    """新建项目资料目录。"""

    service = KnowledgeCategoryService(db)
    category = service.create_category(payload.model_copy(update={"scope_type": "project", "project_id": project_id}), current_user)
    tree = service.list_tree(current_user, "project", project_id)
    return success({"category_id": category.id, "tree": [KnowledgeCategoryOut.model_validate(item).model_dump(mode="json") for item in tree]})


@router.put("/{project_id}/directories/{directory_id}", summary="编辑项目资料目录")
def update_project_directory(
    project_id: int,
    directory_id: int,
    payload: KnowledgeCategoryUpdate,
    current_user: User = Depends(require_permission("project:directory:edit")),
    db: Session = Depends(get_db),
) -> dict:
    """编辑项目资料目录。"""

    service = KnowledgeCategoryService(db)
    category_before = service.get_category(directory_id)
    if category_before.scope_type != "project" or category_before.project_id != project_id:
        raise AppException("项目资料目录不存在", status_code=404, code=404)
    category = service.update_category(directory_id, payload, current_user)
    tree = service.list_tree(current_user, "project", project_id)
    return success({"category_id": category.id, "tree": [KnowledgeCategoryOut.model_validate(item).model_dump(mode="json") for item in tree]})


@router.delete("/{project_id}/directories/{directory_id}", summary="删除项目资料目录")
def delete_project_directory(
    project_id: int,
    directory_id: int,
    current_user: User = Depends(require_permission("project:directory:delete")),
    db: Session = Depends(get_db),
) -> dict:
    """软删除空项目资料目录。"""

    service = KnowledgeCategoryService(db)
    category = service.get_category(directory_id)
    if category.scope_type != "project" or category.project_id != project_id:
        raise AppException("项目资料目录不存在", status_code=404, code=404)
    service.delete_category(directory_id, current_user)
    return success({"deleted": True, "project_id": project_id})


@router.post("/{project_id}/directories/init-template", summary="初始化项目资料目录模板")
def init_project_directory_template(
    project_id: int,
    current_user: User = Depends(require_permission("project:directory:create")),
    db: Session = Depends(get_db),
) -> dict:
    """初始化默认项目资料目录模板。"""

    service = KnowledgeCategoryService(db)
    result = service.init_default_project_template(project_id, current_user)
    tree = service.list_tree(current_user, "project", project_id)
    return success({**result, "tree": [KnowledgeCategoryOut.model_validate(item).model_dump(mode="json") for item in tree]})


@router.get("/{project_id}/members", summary="项目成员")
def list_members(
    project_id: int,
    current_user: User = Depends(require_permission("project:view")),
    db: Session = Depends(get_db),
) -> dict:
    """查询项目成员。"""

    members = ProjectService(db).list_members(project_id, current_user)
    return success([ProjectMemberOut.model_validate(item).model_dump(mode="json") for item in members])


@router.post("/{project_id}/members", summary="新增项目成员")
def add_member(
    project_id: int,
    payload: ProjectMemberCreate,
    current_user: User = Depends(require_permission("project:edit")),
    db: Session = Depends(get_db),
) -> dict:
    """新增项目成员。"""

    member = ProjectService(db).add_member(project_id, payload, current_user)
    return success(ProjectMemberOut.model_validate(member).model_dump(mode="json"))


@router.delete("/{project_id}/members/{user_id}", summary="删除项目成员")
def delete_member(
    project_id: int,
    user_id: int,
    current_user: User = Depends(require_permission("project:edit")),
    db: Session = Depends(get_db),
) -> dict:
    """删除项目成员。"""

    ProjectService(db).delete_member(project_id, user_id, current_user)
    return success({"deleted": True})


def _ensure_document_in_project(document_id: int, project_id: int, current_user: User, db: Session):
    document = DocumentService(db).get_document(document_id, current_user)
    if document.project_id != project_id:
        raise AppException("项目资料不存在", status_code=404, code=404)
    return document


@router.get("/{project_id}/overview", summary="项目概览")
def get_project_overview(
    project_id: int,
    current_user: User = Depends(require_permission("project:view")),
    db: Session = Depends(get_db),
) -> dict:
    return success(ProjectService(db).get_project_overview(project_id, current_user))


@router.get("/{project_id}/documents", summary="项目资料列表")
def list_project_documents(
    project_id: int,
    keyword: str | None = None,
    directory_id: int | None = None,
    category_id: int | None = None,
    status: str | None = None,
    security_level: str | None = None,
    parse_status: str | None = None,
    index_status: str | None = None,
    document_type: str | None = None,
    discipline: str | None = None,
    upload_user_id: int | None = None,
    current_user: User = Depends(require_permission("project:view")),
    db: Session = Depends(get_db),
) -> dict:
    target_directory_id = directory_id or category_id
    documents = DocumentService(db).list_documents(
        current_user,
        project_id=project_id,
        category_id=target_directory_id,
        index_status=index_status,
        knowledge_type="project",
        keyword=keyword,
    )
    if status is not None:
        documents = [item for item in documents if item.status == status]
    if security_level is not None:
        documents = [item for item in documents if item.security_level == security_level]
    if parse_status is not None:
        documents = [item for item in documents if item.parse_status == parse_status]
    if document_type is not None:
        documents = [item for item in documents if item.document_type == document_type]
    if discipline is not None:
        documents = [item for item in documents if item.discipline == discipline]
    if upload_user_id is not None:
        documents = [item for item in documents if (item.upload_user_id or item.created_by) == upload_user_id]
    return success([DocumentOut.model_validate(item).model_dump(mode="json") for item in documents])


@router.get("/{project_id}/documents/page", summary="项目资料分页列表")
def list_project_documents_page(
    project_id: int,
    page: int = 1,
    page_size: int = 10,
    keyword: str | None = None,
    directory_id: int | None = None,
    category_id: int | None = None,
    status: str | None = None,
    security_level: str | None = None,
    parse_status: str | None = None,
    index_status: str | None = None,
    document_type: str | None = None,
    discipline: str | None = None,
    upload_user_id: int | None = None,
    current_user: User = Depends(require_permission("project:view")),
    db: Session = Depends(get_db),
) -> dict:
    target_directory_id = directory_id or category_id
    result = DocumentService(db).list_project_documents_page(
        current_user,
        project_id=project_id,
        page=page,
        page_size=page_size,
        category_id=target_directory_id,
        keyword=keyword,
        status=status,
        security_level=security_level,
        parse_status=parse_status,
        index_status=index_status,
        document_type=document_type,
        discipline=discipline,
        upload_user_id=upload_user_id,
    )
    return success(
        {
            **result,
            "items": [DocumentOut.model_validate(item).model_dump(mode="json") for item in result["items"]],
        }
    )


@router.post("/{project_id}/documents/upload", summary="上传项目资料")
async def upload_project_document(
    project_id: int,
    file: UploadFile = File(...),
    directory_id: int | None = Form(default=None),
    category_id: int | None = Form(default=None),
    security_level: str | None = Form(default=None),
    current_user: User = Depends(require_permission("project:upload")),
    db: Session = Depends(get_db),
) -> dict:
    target_directory_id = directory_id or category_id
    if target_directory_id is None:
        raise AppException("上传项目资料必须选择目录")
    knowledge_base = KnowledgeBaseService(db).get_project_base(project_id, current_user, ("project:upload",))
    document = await DocumentService(db).upload_document(knowledge_base.id, file, current_user, target_directory_id, security_level)
    return success(DocumentOut.model_validate(document).model_dump(mode="json"))


@router.get("/{project_id}/documents/{document_id}", summary="项目资料详情")
def get_project_document(
    project_id: int,
    document_id: int,
    current_user: User = Depends(require_permission("project:view")),
    db: Session = Depends(get_db),
) -> dict:
    document = _ensure_document_in_project(document_id, project_id, current_user, db)
    return success(DocumentOut.model_validate(document).model_dump(mode="json"))


@router.put("/{project_id}/documents/{document_id}", summary="编辑项目资料")
def update_project_document(
    project_id: int,
    document_id: int,
    payload: DocumentMetadataUpdate,
    current_user: User = Depends(require_permission("project:document:edit")),
    db: Session = Depends(get_db),
) -> dict:
    _ensure_document_in_project(document_id, project_id, current_user, db)
    document = DocumentService(db).update_document_metadata(document_id, payload, current_user)
    return success(DocumentOut.model_validate(document).model_dump(mode="json"))


@router.delete("/{project_id}/documents/{document_id}", summary="删除项目资料")
def delete_project_document(
    project_id: int,
    document_id: int,
    current_user: User = Depends(require_permission("project:document:delete")),
    db: Session = Depends(get_db),
) -> dict:
    _ensure_document_in_project(document_id, project_id, current_user, db)
    result = DocumentService(db).delete_document(document_id, current_user)
    return success(DocumentDeleteOut.model_validate(result).model_dump(mode="json"))


@router.post("/{project_id}/documents/{document_id}/publish", summary="发布项目资料")
def publish_project_document(
    project_id: int,
    document_id: int,
    current_user: User = Depends(require_permission("project:submit-review")),
    db: Session = Depends(get_db),
) -> dict:
    _ensure_document_in_project(document_id, project_id, current_user, db)
    document = DocumentService(db).publish_document(document_id, current_user)
    return success(DocumentOut.model_validate(document).model_dump(mode="json"))


@router.post("/{project_id}/documents/{document_id}/retry-parse", summary="重试解析项目资料")
def retry_parse_project_document(
    project_id: int,
    document_id: int,
    version_no: int | None = None,
    current_user: User = Depends(require_permission("project:document:retry-parse")),
    db: Session = Depends(get_db),
) -> dict:
    _ensure_document_in_project(document_id, project_id, current_user, db)
    service = DocumentService(db)
    if version_no is not None:
        return success(service.parse_document_version(document_id, version_no, current_user))
    return success(service.parse_document(document_id, current_user))


@router.post("/{project_id}/documents/{document_id}/retry-index", summary="重试索引项目资料")
def retry_index_project_document(
    project_id: int,
    document_id: int,
    version_no: int | None = None,
    current_user: User = Depends(require_permission("project:document:retry-index")),
    db: Session = Depends(get_db),
) -> dict:
    _ensure_document_in_project(document_id, project_id, current_user, db)
    task = DocumentService(db).create_index_build_task(document_id, current_user, version_no)
    return success(IndexTaskOut.model_validate(task).model_dump(mode="json"))


@router.post("/{project_id}/documents/{document_id}/security-level", summary="修改项目资料密级")
def update_project_document_security_level(
    project_id: int,
    document_id: int,
    payload: DocumentSecurityLevelUpdate,
    current_user: User = Depends(require_permission("project:document:security-update")),
    db: Session = Depends(get_db),
) -> dict:
    _ensure_document_in_project(document_id, project_id, current_user, db)
    document = DocumentService(db).update_document_security_level(document_id, payload.security_level, current_user)
    return success(DocumentOut.model_validate(document).model_dump(mode="json"))


@router.get("/{project_id}/documents/{document_id}/versions", summary="项目资料版本列表")
def list_project_document_versions(
    project_id: int,
    document_id: int,
    current_user: User = Depends(require_permission("project:document:version-view")),
    db: Session = Depends(get_db),
) -> dict:
    _ensure_document_in_project(document_id, project_id, current_user, db)
    versions = DocumentService(db).list_versions(document_id, current_user)
    return success([DocumentVersionOut.model_validate(item).model_dump(mode="json") for item in versions])


@router.post("/{project_id}/documents/{document_id}/versions", summary="上传项目资料新版本")
async def create_project_document_version(
    project_id: int,
    document_id: int,
    file: UploadFile = File(...),
    change_summary: str | None = Form(default=None),
    version_note: str | None = Form(default=None),
    directory_id: int | None = Form(default=None),
    category_id: int | None = Form(default=None),
    current_user: User = Depends(require_permission("project:document:version-create")),
    db: Session = Depends(get_db),
) -> dict:
    _ensure_document_in_project(document_id, project_id, current_user, db)
    target_category_id = directory_id or category_id
    version = await DocumentService(db).create_version(document_id, file, current_user, change_summary or version_note, target_category_id)
    return success(DocumentVersionOut.model_validate(version).model_dump(mode="json"))


@router.post("/{project_id}/documents/{document_id}/versions/{version_id}/set-current", summary="设置项目资料当前版本")
def set_project_document_current_version(
    project_id: int,
    document_id: int,
    version_id: int,
    current_user: User = Depends(require_permission("project:document:version-set-current")),
    db: Session = Depends(get_db),
) -> dict:
    _ensure_document_in_project(document_id, project_id, current_user, db)
    document = DocumentService(db).set_current_version(document_id, version_id, current_user)
    return success(DocumentOut.model_validate(document).model_dump(mode="json"))


@router.post("/{project_id}/chat", summary="项目问答")
def project_chat(
    project_id: int,
    payload: ChatCompletionRequest,
    current_user: User = Depends(require_permission("project:chat")),
    db: Session = Depends(get_db),
) -> dict:
    request = payload.model_copy(update={"chat_type": "project_chat", "project_id": project_id})
    return success(ChatService(db).complete(request, current_user))

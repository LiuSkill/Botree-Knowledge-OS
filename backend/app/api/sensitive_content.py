"""敏感内容配置管理 API。"""

import json
from datetime import datetime

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import require_permission
from app.core.database import get_db
from app.core.response import success
from app.models.project import Project
from app.models.user import Role, User
from app.repositories.sensitive_content_repository import SensitiveContentRepository
from app.schemas.sensitive_content import RoleSensitivePermissionSave, RuleTestRequest, SensitiveRuleOut, SensitiveRulePayload, SensitiveTypeOut, SensitiveTypePayload
from app.services.sensitive_content_service import SensitiveContentManagementService, SensitiveRuleService, SensitiveRuntimeFilter

router = APIRouter(prefix="/sensitive-content", tags=["敏感内容管理"])


@router.get("/types")
def list_types(_: User = Depends(require_permission("system:sensitive-content:view")), db: Session = Depends(get_db)) -> dict:
    return success([SensitiveTypeOut.model_validate(item).model_dump(mode="json") for item in SensitiveContentRepository(db).list_types()])


@router.post("/types")
def create_type(payload: SensitiveTypePayload, _: User = Depends(require_permission("system:sensitive-content:type-create")), db: Session = Depends(get_db)) -> dict:
    item = SensitiveContentManagementService(db).save_type(payload.model_dump())
    return success(SensitiveTypeOut.model_validate(item).model_dump(mode="json"))


@router.put("/types/{item_id:int}")
def update_type(item_id: int, payload: SensitiveTypePayload, _: User = Depends(require_permission("system:sensitive-content:type-edit")), db: Session = Depends(get_db)) -> dict:
    item = SensitiveContentManagementService(db).save_type(payload.model_dump(), item_id)
    return success(SensitiveTypeOut.model_validate(item).model_dump(mode="json"))


@router.get("/rules")
def list_rules(_: User = Depends(require_permission("system:sensitive-content:view")), db: Session = Depends(get_db)) -> dict:
    service = SensitiveContentManagementService(db)
    return success([SensitiveRuleOut.model_validate(service.rule_dict(item)).model_dump(mode="json") for item in service.repository.list_rules()])


@router.post("/rules")
def create_rule(payload: SensitiveRulePayload, _: User = Depends(require_permission("system:sensitive-content:rule-create")), db: Session = Depends(get_db)) -> dict:
    service = SensitiveContentManagementService(db)
    return success(SensitiveRuleOut.model_validate(service.rule_dict(service.save_rule(payload.model_dump()))).model_dump(mode="json"))


@router.put("/rules/{item_id:int}")
def update_rule(item_id: int, payload: SensitiveRulePayload, _: User = Depends(require_permission("system:sensitive-content:rule-edit")), db: Session = Depends(get_db)) -> dict:
    service = SensitiveContentManagementService(db)
    return success(SensitiveRuleOut.model_validate(service.rule_dict(service.save_rule(payload.model_dump(), item_id))).model_dump(mode="json"))


@router.post("/rules/test")
def test_rules(payload: RuleTestRequest, _: User = Depends(require_permission("system:sensitive-content:rule-test")), db: Session = Depends(get_db)) -> dict:
    _, rules = SensitiveRuleService(db).load()
    rule_items = SensitiveContentRepository(db).list_rules()
    rule_id_by_code = {item.code: item.id for item in rule_items}
    rule_name_by_code = {item.code: item.name for item in rule_items}
    if payload.rule_id is not None:
        rules = tuple(rule for rule in rules if rule_id_by_code.get(rule.code) == payload.rule_id and payload.rule_enabled)
    allowed = set()
    if payload.role_id is not None:
        allowed = SensitiveContentRepository(db).allowed_types({payload.role_id})
    result = SensitiveRuntimeFilter().filter(payload.content, allowed, rules)
    return success({"safe_content": result.safe_content, "redacted": result.redacted, "redaction_types": list(result.redaction_types), "redaction_count": result.redaction_count, "matched_rule_codes": list(result.matched_rule_codes), "matched_rule_names": [rule_name_by_code.get(code, code) for code in result.matched_rule_codes]})


@router.get("/roles/{role_id:int}/permissions")
def get_role_permissions(role_id: int, _: User = Depends(require_permission("system:sensitive-content:view")), db: Session = Depends(get_db)) -> dict:
    repo = SensitiveContentRepository(db)
    saved = {item.sensitive_type_code: item.can_view for item in repo.list_role_permissions(role_id)}
    return success({item.code: saved.get(item.code, False) for item in repo.list_types()})


@router.get("/roles/permissions/matrix")
def permission_matrix(_: User = Depends(require_permission("system:sensitive-content:view")), db: Session = Depends(get_db)) -> dict:
    repo = SensitiveContentRepository(db)
    role_items = repo.list_roles()
    type_items = repo.list_types()
    matrix = []
    for role in role_items:
        saved = {item.sensitive_type_code: item.can_view for item in repo.list_role_permissions(role.id)}
        matrix.append({"role_id": role.id, "role_name": role.name, "permissions": {item.code: saved.get(item.code, False) for item in type_items}})
    return success({"types": [SensitiveTypeOut.model_validate(item).model_dump(mode="json") for item in type_items], "roles": matrix})


@router.put("/roles/{role_id:int}/permissions")
def save_role_permissions(role_id: int, payload: RoleSensitivePermissionSave, _: User = Depends(require_permission("system:sensitive-content:permission-save")), db: Session = Depends(get_db)) -> dict:
    SensitiveContentManagementService(db).save_role_permissions(role_id, payload.permissions)
    return success({"saved": True})


@router.post("/cache/refresh")
def refresh_cache(_: User = Depends(require_permission("system:sensitive-content:cache-refresh"))) -> dict:
    SensitiveRuleService.refresh()
    return success({"refreshed": True})


@router.get("/audits")
def list_audits(
    page: int = 1,
    page_size: int = 20,
    started_at: datetime | None = None,
    ended_at: datetime | None = None,
    user_id: int | None = None,
    sensitive_type: str | None = None,
    final_answer_redacted: bool | None = None,
    chat_type: str | None = None,
    project_id: int | None = None,
    _: User = Depends(require_permission("system:sensitive-content:audit-view")),
    db: Session = Depends(get_db),
) -> dict:
    normalized_page = max(1, page)
    normalized_size = min(100, max(1, page_size))
    items, total = SensitiveContentRepository(db).list_audits(
        offset=(normalized_page - 1) * normalized_size,
        limit=normalized_size,
        started_at=started_at,
        ended_at=ended_at,
        user_id=user_id,
        sensitive_type=sensitive_type,
        final_answer_redacted=final_answer_redacted,
        chat_type=chat_type,
        project_id=project_id,
    )
    user_ids = {item.user_id for item in items if item.user_id is not None}
    project_ids = {item.project_id for item in items if item.project_id is not None}
    role_ids = {role_id for item in items for role_id in json.loads(item.role_ids)}
    users = {item.id: item.real_name or item.username for item in db.query(User).filter(User.id.in_(user_ids)).all()} if user_ids else {}
    projects = {item.id: item.name for item in db.query(Project).filter(Project.id.in_(project_ids)).all()} if project_ids else {}
    roles = {item.id: item.name for item in db.query(Role).filter(Role.id.in_(role_ids)).all()} if role_ids else {}
    return success({
        "items": [
            {
                "id": item.id, "user_id": item.user_id, "username": users.get(item.user_id),
                "role_ids": json.loads(item.role_ids), "role_names": [roles.get(role_id, f"角色#{role_id}") for role_id in json.loads(item.role_ids)],
                "message_id": item.message_id, "chat_type": item.chat_type, "project_id": item.project_id,
                "project_name": projects.get(item.project_id),
                "redaction_types": json.loads(item.redaction_types), "redaction_count": item.redaction_count,
                "final_answer_redacted": item.final_answer_redacted, "created_at": item.created_at.isoformat(),
            }
            for item in items
        ],
        "total": total, "page": normalized_page, "page_size": normalized_size,
    })

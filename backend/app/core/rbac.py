"""
RBAC Permission Registry.

职责：
1. 统一维护后端权限种子、前端动态菜单和按钮级权限点。
2. 菜单权限控制路由与导航可见性，操作权限控制按钮与 API。
3. 操作权限必须显式授予，并且只能挂靠在已授权菜单下，避免孤立按钮权限绕过页面访问控制。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable


@dataclass(frozen=True)
class MenuNode:
    """菜单权限节点，叶子节点需要绑定真实前端路由 path。"""

    id: str
    name: str
    path: str | None = None
    children: tuple["MenuNode", ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class ActionPermission:
    """按钮/API 级操作权限定义，对应前端 v-permission 与后端 require_permission。"""

    action: str
    name: str
    code: str


@dataclass(frozen=True)
class ActionGroup:
    """按业务模块分组的按钮/API 权限。"""

    module: str
    module_name: str
    menu_ids: tuple[str, ...]
    actions: tuple[ActionPermission, ...]


MENU_TREE: tuple[MenuNode, ...] = (
    MenuNode("dashboard", "首页", "/dashboard"),
    MenuNode("knowledge", "知识中心", "/knowledge"),
    MenuNode("project", "项目中心", "/projects"),
    MenuNode("authorization", "知识授权中心", "/authorization"),
    MenuNode("review", "审核中心", "/reviews"),
    MenuNode(
        "process_config",
        "工艺配置",
        "/process-config",
        (
            MenuNode("process_config:material", "原料库", "/process-config/materials"),
            MenuNode("process_config:product", "产品库", "/process-config/products"),
            MenuNode("process_config:consumable", "消耗品库", "/process-config/consumables"),
            MenuNode("process_config:public_service", "公共服务库", "/process-config/public-services"),
            MenuNode("process_config:labor", "人员成本库", "/process-config/labor-costs"),
            MenuNode("process_config:asset_equipment", "设备资产库", "/process-config/equipment-assets"),
            MenuNode("process_config:asset_infrastructure", "基础设施库", "/process-config/infrastructure-assets"),
            MenuNode("process_config:node", "工艺节点库", "/process-config/nodes"),
            MenuNode("process_config:route", "工艺路线库", "/process-config/routes"),
            MenuNode("process_config:calculator", "快速财务计算器", "/process-config/calculator"),
        ),
    ),
    MenuNode(
        "ai",
        "知识问答",
        None,
        (
            MenuNode("ai:project-chat", "项目问答", "/ai/project-chat"),
            MenuNode("ai:base-chat", "基础问答", "/ai/base-chat"),
        ),
    ),
    MenuNode(
        "system",
        "系统管理",
        "/system",
        (
            MenuNode("system:user", "用户管理", "/system/users"),
            MenuNode("system:department:view", "部门管理", "/system/departments"),
            MenuNode("system:permission", "权限矩阵", "/system/permissions"),
            MenuNode("system:model-config", "模型配置", "/system/model-configs"),
            MenuNode("system:operation-log", "操作日志", "/system/logs"),
            MenuNode("system:qa-audit", "问答审计", "/system/qa-audits"),
            MenuNode("system:sensitive-content", "敏感内容管理", "/system/sensitive-content"),
        ),
    ),
)


ACTION_GROUPS: tuple[ActionGroup, ...] = (
    ActionGroup(
        "dashboard",
        "首页",
        ("dashboard",),
        (
            ActionPermission("view", "查看首页统计", "dashboard:view"),
        ),
    ),
    ActionGroup(
        "knowledge",
        "知识中心",
        ("knowledge",),
        (
            ActionPermission("view", "查看知识资料", "knowledge:view"),
            ActionPermission("create", "新增知识分类", "knowledge:create"),
            ActionPermission("edit", "编辑知识分类/资料", "knowledge:edit"),
            ActionPermission("upload", "上传知识文档", "knowledge:upload"),
            ActionPermission("submit-review", "提交知识资料审核", "knowledge:submit-review"),
            ActionPermission("download", "下载知识资料", "knowledge:download"),
            ActionPermission("delete", "删除知识资料", "knowledge:delete"),
        ),
    ),
    ActionGroup(
        "project",
        "项目中心",
        ("project",),
        (
            ActionPermission("view", "查看项目/项目资料", "project:view"),
            ActionPermission("create", "新增项目", "project:create"),
            ActionPermission("edit", "编辑项目", "project:edit"),
            ActionPermission("delete", "删除项目", "project:delete"),
            ActionPermission("chat", "项目问答跳转", "project:chat"),
        ),
    ),
    ActionGroup(
        "project-directory",
        "项目资料目录",
        ("project",),
        (
            ActionPermission("create", "新增项目资料目录", "project:directory:create"),
            ActionPermission("edit", "编辑项目资料目录", "project:directory:edit"),
            ActionPermission("delete", "删除项目资料目录", "project:directory:delete"),
        ),
    ),
    ActionGroup(
        "project-document",
        "项目资料",
        ("project",),
        (
            ActionPermission("upload", "上传项目资料", "project:upload"),
            ActionPermission("submit-review", "提交/发布项目资料", "project:submit-review"),
            ActionPermission("edit", "编辑项目资料元数据", "project:document:edit"),
            ActionPermission("delete", "删除项目资料", "project:document:delete"),
            ActionPermission("preview", "预览项目资料", "project:document:preview"),
            ActionPermission("download", "下载项目资料", "project:document:download"),
            ActionPermission("retry-parse", "重试项目资料解析", "project:document:retry-parse"),
            ActionPermission("retry-index", "重试项目资料索引", "project:document:retry-index"),
            ActionPermission("security-update", "保存项目资料密级", "project:document:security-update"),
            ActionPermission("version-view", "查看项目资料版本", "project:document:version-view"),
            ActionPermission("version-create", "上传项目资料新版本", "project:document:version-create"),
            ActionPermission("version-set-current", "设置项目资料当前版本", "project:document:version-set-current"),
        ),
    ),
    ActionGroup(
        "authorization",
        "知识授权中心",
        ("authorization",),
        (
            ActionPermission("view", "查看授权", "authorization:view"),
        ),
    ),
    ActionGroup(
        "review",
        "审核中心",
        ("review",),
        (
            ActionPermission("view", "查看审核记录", "review:view"),
            ActionPermission("approve", "审核通过", "review:approve"),
            ActionPermission("reject", "审核驳回", "review:reject"),
            ActionPermission("build-index", "解析并构建索引", "review:build-index"),
        ),
    ),
    ActionGroup(
        "process-config-material",
        "原料库",
        ("process_config:material",),
        (
            ActionPermission("view", "查看原料", "process_config:material:view"),
            ActionPermission("create", "新增原料", "process_config:material:create"),
            ActionPermission("update", "编辑原料", "process_config:material:update"),
            ActionPermission("delete", "删除原料", "process_config:material:delete"),
            ActionPermission("import", "导入原料", "process_config:material:import"),
            ActionPermission("export", "导出原料", "process_config:material:export"),
        ),
    ),
    ActionGroup(
        "process-config-product",
        "产品库",
        ("process_config:product",),
        (
            ActionPermission("view", "查看产品", "process_config:product:view"),
            ActionPermission("create", "新增产品", "process_config:product:create"),
            ActionPermission("update", "编辑产品", "process_config:product:update"),
            ActionPermission("delete", "删除产品", "process_config:product:delete"),
            ActionPermission("import", "导入产品", "process_config:product:import"),
            ActionPermission("export", "导出产品", "process_config:product:export"),
        ),
    ),
    ActionGroup(
        "process-config-consumable",
        "消耗品库",
        ("process_config:consumable",),
        (
            ActionPermission("view", "查看消耗品", "process_config:consumable:view"),
            ActionPermission("create", "新增消耗品", "process_config:consumable:create"),
            ActionPermission("update", "编辑消耗品", "process_config:consumable:update"),
            ActionPermission("delete", "删除消耗品", "process_config:consumable:delete"),
            ActionPermission("import", "导入消耗品", "process_config:consumable:import"),
            ActionPermission("export", "导出消耗品", "process_config:consumable:export"),
        ),
    ),
    ActionGroup(
        "process-config-public-service",
        "公共服务库",
        ("process_config:public_service",),
        (
            ActionPermission("view", "查看公共服务", "process_config:public_service:view"),
            ActionPermission("create", "新增公共服务", "process_config:public_service:create"),
            ActionPermission("update", "编辑公共服务", "process_config:public_service:update"),
            ActionPermission("delete", "删除公共服务", "process_config:public_service:delete"),
            ActionPermission("import", "导入公共服务", "process_config:public_service:import"),
            ActionPermission("export", "导出公共服务", "process_config:public_service:export"),
        ),
    ),
    ActionGroup("process-config-labor", "人员成本库", ("process_config:labor",), (ActionPermission("view", "查看人员成本", "process_config:labor:view"), ActionPermission("create", "新增人员成本", "process_config:labor:create"), ActionPermission("update", "编辑人员成本", "process_config:labor:update"), ActionPermission("delete", "删除人员成本", "process_config:labor:delete"))),
    ActionGroup("process-config-asset", "设备/基础设施资产库", ("process_config:asset_equipment",), (ActionPermission("view", "查看设备/基础设施资产", "process_config:asset:view"), ActionPermission("create", "新增设备/基础设施资产", "process_config:asset:create"), ActionPermission("update", "编辑设备/基础设施资产", "process_config:asset:update"), ActionPermission("delete", "删除设备/基础设施资产", "process_config:asset:delete"))),
    ActionGroup(
        "process-config-node",
        "工艺节点库",
        ("process_config:node",),
        (
            ActionPermission("view", "查看工艺节点", "process_config:node:view"),
            ActionPermission("create", "新增工艺节点", "process_config:node:create"),
            ActionPermission("update", "编辑工艺节点", "process_config:node:update"),
            ActionPermission("delete", "删除工艺节点", "process_config:node:delete"),
            ActionPermission("import", "导入工艺节点", "process_config:node:import"),
            ActionPermission("export", "导出工艺节点", "process_config:node:export"),
        ),
    ),
    ActionGroup(
        "process-config-route",
        "工艺路线库",
        ("process_config:route",),
        (
            ActionPermission("view", "查看工艺路线", "process_config:route:view"),
            ActionPermission("create", "新增工艺路线", "process_config:route:create"),
            ActionPermission("update", "编辑工艺路线", "process_config:route:update"),
            ActionPermission("delete", "删除工艺路线", "process_config:route:delete"),
            ActionPermission("import", "导入工艺路线", "process_config:route:import"),
            ActionPermission("export", "导出工艺路线", "process_config:route:export"),
            ActionPermission("version", "管理工艺路线版本", "process_config:route:version"),
            ActionPermission("preview", "线路预览", "process_config:route:preview"),
        ),
    ),
    ActionGroup(
        "process-config-calculator",
        "快速财务计算器",
        ("process_config:calculator",),
        (
            ActionPermission("view", "查看快速财务计算器", "process_config:calculator:view"),
            ActionPermission("calculate", "执行快速财务测算", "process_config:calculator:calculate"),
        ),
    ),
    ActionGroup(
        "ai-project-chat",
        "项目问答",
        ("ai:project-chat",),
        (
            ActionPermission("view", "进入项目问答页面", "ai:project-chat:view"),
            ActionPermission("create-session", "新建项目问答会话", "ai:project-chat:create-session"),
            ActionPermission("send-message", "发送项目问答消息", "ai:project-chat:send-message"),
            ActionPermission("manage-session", "重命名/置顶/收藏项目问答会话", "ai:project-chat:manage-session"),
            ActionPermission("delete-session", "删除项目问答会话", "ai:project-chat:delete-session"),
            ActionPermission("feedback", "反馈项目问答答案", "ai:project-chat:feedback"),
        ),
    ),
    ActionGroup(
        "ai-base-chat",
        "基础问答",
        ("ai:base-chat",),
        (
            ActionPermission("view", "进入基础问答页面", "ai:base-chat:view"),
            ActionPermission("create-session", "新建基础问答会话", "ai:base-chat:create-session"),
            ActionPermission("send-message", "发送基础问答消息", "ai:base-chat:send-message"),
            ActionPermission("manage-session", "重命名/置顶/收藏基础问答会话", "ai:base-chat:manage-session"),
            ActionPermission("delete-session", "删除基础问答会话", "ai:base-chat:delete-session"),
            ActionPermission("feedback", "反馈基础问答答案", "ai:base-chat:feedback"),
        ),
    ),
    ActionGroup(
        "system-user",
        "用户管理",
        ("system:user",),
        (
            ActionPermission("view", "查看用户列表", "system:user:view"),
            ActionPermission("create", "新增用户账号", "system:user:create"),
            ActionPermission("edit", "编辑用户资料", "system:user:edit"),
            ActionPermission("disable", "启用/停用用户", "system:user:disable"),
            ActionPermission("reset-password", "重置用户密码", "system:user:reset-password"),
            ActionPermission("delete", "删除用户账号", "system:user:delete"),
        ),
    ),
    ActionGroup(
        "system-department",
        "部门管理",
        ("system:department:view",),
        (
            ActionPermission("create", "新增部门", "system:department:create"),
            ActionPermission("edit", "编辑部门", "system:department:edit"),
            ActionPermission("delete", "删除部门", "system:department:delete"),
            ActionPermission("enable", "启用部门", "system:department:enable"),
            ActionPermission("disable", "停用部门", "system:department:disable"),
            ActionPermission("view-detail", "查看部门详情", "system:department:view-detail"),
        ),
    ),
    ActionGroup(
        "system-permission",
        "权限矩阵",
        ("system:permission",),
        (
            ActionPermission("view", "查看权限矩阵", "system:permission:view"),
            ActionPermission("create-role", "新增角色", "system:permission:create-role"),
            ActionPermission("edit-role", "编辑角色", "system:permission:edit-role"),
            ActionPermission("delete-role", "删除角色", "system:permission:delete-role"),
            ActionPermission("save", "保存角色权限", "system:permission:save"),
        ),
    ),
    ActionGroup(
        "system-model",
        "模型配置",
        ("system:model-config",),
        (
            ActionPermission("view", "查看模型配置", "system:model:view"),
            ActionPermission("create", "新增模型配置", "system:model:create"),
            ActionPermission("edit", "编辑/启停模型配置", "system:model:edit"),
            ActionPermission("test", "测试模型连接", "system:model:test"),
            ActionPermission("set-default", "设置默认模型", "system:model:set-default"),
            ActionPermission("delete", "删除模型配置", "system:model:delete"),
        ),
    ),
    ActionGroup(
        "system-log",
        "操作日志",
        ("system:operation-log",),
        (
            ActionPermission("view", "查看操作日志", "system:log:view"),
        ),
    ),
    ActionGroup(
        "system-qa-audit",
        "问答审计",
        ("system:qa-audit",),
        (
            ActionPermission("view", "查看问答审计", "system:qa-audit:view"),
        ),
    ),
    ActionGroup(
        "system-sensitive-content",
        "敏感内容管理",
        ("system:sensitive-content",),
        (
            ActionPermission("view", "查看敏感内容配置", "system:sensitive-content:view"),
            ActionPermission("type-create", "新增敏感类型", "system:sensitive-content:type-create"),
            ActionPermission("type-edit", "编辑/启停敏感类型", "system:sensitive-content:type-edit"),
            ActionPermission("rule-create", "新增敏感规则", "system:sensitive-content:rule-create"),
            ActionPermission("rule-edit", "编辑/启停敏感规则", "system:sensitive-content:rule-edit"),
            ActionPermission("rule-test", "测试敏感规则", "system:sensitive-content:rule-test"),
            ActionPermission("permission-save", "保存角色敏感权限", "system:sensitive-content:permission-save"),
            ActionPermission("cache-refresh", "刷新敏感规则缓存", "system:sensitive-content:cache-refresh"),
            ActionPermission("audit-view", "查看脱敏审计", "system:sensitive-content:audit-view"),
        ),
    ),
)


def iter_menu_nodes(nodes: Iterable[MenuNode] = MENU_TREE) -> Iterable[MenuNode]:
    """深度优先遍历菜单树。"""

    for node in nodes:
        yield node
        yield from iter_menu_nodes(node.children)


def menu_permission_codes() -> set[str]:
    """返回需要进入权限矩阵的菜单权限编码。"""

    return {node.id for node in iter_menu_nodes() if node.path and not node.children}


def action_permission_codes() -> set[str]:
    """返回需要进入权限矩阵的按钮/API 权限编码。"""

    return {action.code for group in ACTION_GROUPS for action in group.actions}


def action_page_bindings() -> dict[str, set[str]]:
    """返回操作权限与页面菜单权限的绑定关系。"""

    bindings: dict[str, set[str]] = {}
    for group in ACTION_GROUPS:
        for action in group.actions:
            bindings.setdefault(action.code, set()).update(group.menu_ids)
    return bindings


def linked_action_codes(menu_codes: set[str]) -> set[str]:
    """根据已授权菜单返回可挂靠在这些页面下的候选操作权限码。"""

    return {
        action.code
        for group in ACTION_GROUPS
        if set(group.menu_ids) & menu_codes
        for action in group.actions
    }


def sync_menu_action_permission_codes(permission_codes: set[str]) -> set[str]:
    """
    修剪角色权限，保留菜单权限和已挂靠到授权菜单下的显式操作权限。

    业务规则：
    - 菜单权限控制路由和导航；
    - 按钮/API 权限必须显式授予；
    - 未授权页面下的按钮/API 权限会被移除，避免孤立操作权限。
    """

    menu_codes = permission_codes & menu_permission_codes()
    explicit_action_codes = {
        code
        for code in permission_codes & action_permission_codes()
        if action_page_bindings().get(code, set()) & menu_codes
    }
    return menu_codes | explicit_action_codes


def filter_bound_action_codes(permission_codes: set[str]) -> set[str]:
    """返回当前角色显式拥有且已挂靠到授权菜单下的按钮/API 权限。"""

    menu_codes = permission_codes & menu_permission_codes()
    return {
        code
        for code in permission_codes & action_permission_codes()
        if action_page_bindings().get(code, set()) & menu_codes
    }


def user_permission_codes(user: Any) -> set[str]:
    """汇总用户启用角色下的原始权限编码。"""

    codes: set[str] = set()
    for role in getattr(user, "roles", []):
        if not role.enabled:
            continue
        for permission in role.permissions:
            codes.add(permission.code)
    return codes


def is_admin(user: Any) -> bool:
    """系统管理员拥有当前真实权限定义中的全部权限。"""

    return any(role.code == "admin" and role.enabled for role in getattr(user, "roles", []))


def has_permission(user: Any, permission_code: str) -> bool:
    """按当前菜单绑定关系判断用户是否拥有指定权限。"""

    if is_admin(user):
        return True
    permission_codes = sync_menu_action_permission_codes(user_permission_codes(user))
    return permission_code in permission_codes


def permission_catalog() -> list[dict[str, str]]:
    """
    生成可写入 permissions 表的权限定义。

    说明：菜单权限负责路由和导航可见性，操作权限负责按钮/API 控制。
    """

    records: list[dict[str, str]] = []
    for node in iter_menu_nodes():
        if node.path and not node.children:
            module, action = _split_permission_code(node.id, default_action="access")
            records.append(
                {
                    "module": module,
                    "action": action,
                    "code": node.id,
                    "description": f"菜单访问：{node.name}",
                }
            )
    for group in ACTION_GROUPS:
        for action in group.actions:
            module, action_name = _split_permission_code(action.code, default_action=action.action)
            records.append(
                {
                    "module": module,
                    "action": action_name,
                    "code": action.code,
                    "description": f"{group.module_name}：{action.name}",
                }
            )
    return records


def _split_permission_code(code: str, default_action: str) -> tuple[str, str]:
    """将权限码拆为 module/action，兼容 dashboard 这类单段菜单码。"""

    if ":" not in code:
        return code, default_action
    module, action = code.rsplit(":", 1)
    return module, action

"""
RBAC Permission Registry.

职责：
1. 统一维护后端权限种子、前端动态菜单和按钮级权限点。
2. 菜单权限控制路由与导航可见性，操作权限控制按钮与 API。
3. 操作权限必须挂靠在已授权菜单下，避免孤立按钮权限绕过页面访问控制。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable


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
            MenuNode("system:permission", "权限矩阵", "/system/permissions"),
            MenuNode("system:model-config", "模型配置", "/system/model-configs"),
            MenuNode("system:operation-log", "操作日志", "/system/logs"),
            MenuNode("system:qa-audit", "问答审计", "/system/qa-audits"),
        ),
    ),
)

ACTION_GROUPS: tuple[ActionGroup, ...] = (
    ActionGroup(
        "user",
        "用户管理",
        ("system:user",),
        (
            ActionPermission("view", "查看用户列表", "user:view"),
            ActionPermission("create", "新增用户账号", "user:create"),
            ActionPermission("edit", "编辑用户资料", "user:edit"),
            ActionPermission("status", "启用/停用用户", "user:status"),
            ActionPermission("reset-password", "重置用户密码", "user:reset-password"),
            ActionPermission("delete", "删除用户账号", "user:delete"),
        ),
    ),
    ActionGroup(
        "permission",
        "权限矩阵",
        ("system:permission",),
        (
            ActionPermission("view", "查看权限矩阵", "permission:view"),
            ActionPermission("create", "新增角色", "permission:create"),
            ActionPermission("edit", "编辑角色", "permission:edit"),
            ActionPermission("delete", "删除角色", "permission:delete"),
            ActionPermission("save", "保存角色权限", "permission:save"),
        ),
    ),
    ActionGroup(
        "model-config",
        "模型配置",
        ("system:model-config",),
        (
            ActionPermission("view", "查看模型配置", "model-config:view"),
            ActionPermission("create", "新增模型配置", "model-config:create"),
            ActionPermission("edit", "编辑模型配置", "model-config:edit"),
            ActionPermission("set-default", "设为默认模型", "model-config:set-default"),
            ActionPermission("test", "测试模型连接", "model-config:test"),
            ActionPermission("delete", "删除模型配置", "model-config:delete"),
        ),
    ),
    ActionGroup(
        "knowledge",
        "知识中心",
        ("knowledge", "project"),
        (
            ActionPermission("view", "查看知识资料", "knowledge:view"),
            ActionPermission("create", "新增知识分类", "knowledge:create"),
            ActionPermission("edit", "编辑知识分类", "knowledge:edit"),
            ActionPermission("upload", "上传知识文档", "knowledge:upload"),
            ActionPermission("submit-review", "提交文档审核", "knowledge:submit-review"),
            ActionPermission("delete", "删除知识资料", "knowledge:delete"),
        ),
    ),
    ActionGroup(
        "project",
        "项目中心",
        ("project",),
        (
            ActionPermission("view", "查看项目列表", "project:view"),
            ActionPermission("manage", "进入项目管理", "project:manage"),
            ActionPermission("create", "新建项目", "project:create"),
            ActionPermission("update", "编辑项目基本信息", "project:update"),
            ActionPermission("edit", "编辑项目基本信息（兼容旧权限）", "project:edit"),
            ActionPermission("delete", "删除项目", "project:delete"),
            ActionPermission("detail-view", "查看项目详情", "project:detail:view"),
            ActionPermission("document-view", "查看项目资料页", "project:document:view"),
            ActionPermission("chat-view", "查看项目问答页", "project:chat:view"),
        ),
    ),
    ActionGroup(
        "project_directory",
        "项目资料目录",
        ("project",),
        (
            ActionPermission("view", "查看项目目录", "project_directory:view"),
            ActionPermission("create", "新建项目目录", "project_directory:create"),
            ActionPermission("update", "编辑项目目录", "project_directory:update"),
            ActionPermission("delete", "删除项目目录", "project_directory:delete"),
            ActionPermission("init-template", "初始化默认目录模板", "project_directory:init_template"),
        ),
    ),
    ActionGroup(
        "project_document",
        "项目资料",
        ("project",),
        (
            ActionPermission("view", "查看项目资料", "project_document:view"),
            ActionPermission("upload", "上传项目资料", "project_document:upload"),
            ActionPermission("update", "编辑项目资料", "project_document:update"),
            ActionPermission("delete", "删除项目资料", "project_document:delete"),
            ActionPermission("download", "下载项目资料", "project_document:download"),
            ActionPermission("preview", "预览项目资料", "project_document:preview"),
            ActionPermission("publish", "发布项目资料", "project_document:publish"),
            ActionPermission("version-create", "上传项目资料新版本", "project_document:version:create"),
            ActionPermission("version-view", "查看项目资料版本", "project_document:version:view"),
            ActionPermission("retry-parse", "重试项目资料解析", "project_document:retry_parse"),
            ActionPermission("retry-index", "重试项目资料索引", "project_document:retry_index"),
            ActionPermission("ai-toggle", "设置项目资料 AI 问答开关", "project_document:ai_toggle"),
            ActionPermission("security-update", "修改项目资料密级", "project_document:security_update"),
        ),
    ),
    ActionGroup(
        "project_chat",
        "项目问答",
        ("ai:project-chat",),
        (
            ActionPermission("ask", "发起项目问答", "project_chat:ask"),
            ActionPermission("view-history", "查看项目问答历史", "project_chat:view_history"),
            ActionPermission("view-sources", "查看项目问答引用来源", "project_chat:view_sources"),
        ),
    ),
    ActionGroup(
        "project_audit",
        "项目审计",
        ("system:operation-log",),
        (
            ActionPermission("view", "查看项目审计日志", "project_audit:view"),
        ),
    ),
    ActionGroup(
        "review",
        "审核中心",
        ("review", "knowledge"),
        (
            ActionPermission("view", "查看审核任务", "review:view"),
            ActionPermission("review", "审核文档通过/驳回", "review:review"),
            ActionPermission("build-index", "构建文档索引", "review:build-index"),
        ),
    ),
    ActionGroup(
        "ai",
        "智能问答",
        ("ai:project-chat", "ai:base-chat"),
        (
            ActionPermission("chat", "发起智能问答", "ai:chat"),
            ActionPermission("delete-session", "删除问答会话", "ai:delete-session"),
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
    """根据已授权菜单返回可挂靠在这些页面下的操作权限码。"""

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
    - 按钮/API 权限需要显式授予；
    - 未授权页面下的按钮/API 权限会被移除，避免孤立操作权限。
    """

    menu_codes = permission_codes & menu_permission_codes()
    explicit_action_codes = {
        code
        for code in permission_codes & action_permission_codes()
        if action_page_bindings().get(code, set()) & menu_codes
    }
    return menu_codes | explicit_action_codes | linked_action_codes(menu_codes)


def filter_bound_action_codes(permission_codes: set[str]) -> set[str]:
    """返回当前角色显式拥有且已挂靠到授权菜单下的按钮/API 权限。"""

    menu_codes = permission_codes & menu_permission_codes()
    explicit_action_codes = {
        code
        for code in permission_codes & action_permission_codes()
        if action_page_bindings().get(code, set()) & menu_codes
    }
    return explicit_action_codes | linked_action_codes(menu_codes)


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
    module, action = code.split(":", 1)
    return module, action

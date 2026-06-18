"""
RBAC Permission Registry

负责：
1. 维护系统真实菜单路由与按钮级操作权限的统一注册表
2. 为数据库种子、权限矩阵接口和登录态权限拆分提供同一数据源
3. 避免前端静态配置权限点导致权限控制与实际功能脱节
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable


@dataclass(frozen=True)
class MenuNode:
    """菜单权限节点，叶子节点必须绑定前端真实路由 path。"""

    id: str
    name: str
    path: str | None = None
    children: tuple["MenuNode", ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class ActionPermission:
    """按钮级操作权限定义，对应前端 v-permission 权限码。"""

    action: str
    name: str
    code: str


@dataclass(frozen=True)
class ActionGroup:
    """按业务模块分组的按钮级权限。"""

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
    MenuNode("ai:project-chat", "项目问答", "/ai/project-chat"),
    MenuNode("ai:base-chat", "基础问答", "/ai/base-chat"),
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
            ActionPermission("view", "查看", "user:view"),
            ActionPermission("create", "新增", "user:create"),
            ActionPermission("edit", "编辑", "user:edit"),
            ActionPermission("status", "启停", "user:status"),
            ActionPermission("reset-password", "重置密码", "user:reset-password"),
            ActionPermission("delete", "删除", "user:delete"),
        ),
    ),
    ActionGroup(
        "permission",
        "权限矩阵",
        ("system:permission",),
        (
            ActionPermission("view", "查看", "permission:view"),
            ActionPermission("create", "新增角色", "permission:create"),
            ActionPermission("edit", "编辑角色", "permission:edit"),
            ActionPermission("delete", "删除角色", "permission:delete"),
            ActionPermission("save", "保存权限", "permission:save"),
        ),
    ),
    ActionGroup(
        "model-config",
        "模型配置",
        ("system:model-config",),
        (
            ActionPermission("view", "查看", "model-config:view"),
            ActionPermission("create", "新增", "model-config:create"),
            ActionPermission("edit", "编辑", "model-config:edit"),
            ActionPermission("set-default", "设为默认", "model-config:set-default"),
            ActionPermission("test", "测试", "model-config:test"),
            ActionPermission("delete", "删除", "model-config:delete"),
        ),
    ),
    ActionGroup(
        "knowledge",
        "知识中心",
        ("knowledge", "project"),
        (
            ActionPermission("view", "查看", "knowledge:view"),
            ActionPermission("create", "新增", "knowledge:create"),
            ActionPermission("edit", "编辑", "knowledge:edit"),
            ActionPermission("upload", "上传", "knowledge:upload"),
            ActionPermission("submit-review", "提交审核", "knowledge:submit-review"),
            ActionPermission("delete", "删除", "knowledge:delete"),
        ),
    ),
    ActionGroup(
        "project",
        "项目中心",
        ("project",),
        (
            ActionPermission("view", "查看", "project:view"),
            ActionPermission("create", "新增", "project:create"),
            ActionPermission("edit", "编辑", "project:edit"),
            ActionPermission("delete", "删除", "project:delete"),
        ),
    ),
    ActionGroup(
        "review",
        "审核中心",
        ("review", "knowledge"),
        (
            ActionPermission("view", "查看", "review:view"),
            ActionPermission("review", "审核", "review:review"),
            ActionPermission("build-index", "构建索引", "review:build-index"),
        ),
    ),
    ActionGroup(
        "ai",
        "智能问答",
        ("ai:project-chat", "ai:base-chat"),
        (
            ActionPermission("chat", "发起问答", "ai:chat"),
            ActionPermission("delete-session", "删除会话", "ai:delete-session"),
        ),
    ),
)


def iter_menu_nodes(nodes: Iterable[MenuNode] = MENU_TREE) -> Iterable[MenuNode]:
    """深度优先遍历菜单树。"""

    for node in nodes:
        yield node
        yield from iter_menu_nodes(node.children)


def menu_permission_codes() -> set[str]:
    """返回需要进入当前权限矩阵的菜单权限编码。"""

    return {node.id for node in iter_menu_nodes() if node.path and not node.children}


def action_permission_codes() -> set[str]:
    """返回需要进入当前权限矩阵的按钮级权限编码。"""

    return {action.code for group in ACTION_GROUPS for action in group.actions}


def action_page_bindings() -> dict[str, set[str]]:
    """返回按钮权限与页面菜单权限的绑定关系。"""

    return {action.code: set(group.menu_ids) for group in ACTION_GROUPS for action in group.actions}


def filter_bound_action_codes(permission_codes: set[str]) -> set[str]:
    """仅保留已拥有所属页面权限的按钮权限。"""

    bindings = action_page_bindings()
    return {
        code
        for code in permission_codes & action_permission_codes()
        if bindings.get(code, set()) & permission_codes
    }


def permission_catalog() -> list[dict[str, str]]:
    """
    生成可写入 permissions 表的权限定义。

    说明：
        菜单权限负责路由和导航可见性，按钮权限负责 v-permission 显隐。
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

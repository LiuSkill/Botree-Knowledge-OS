# System Management Module

## 功能

提供系统管理页面，覆盖用户管理、权限矩阵、模型配置、操作日志和问答审计。
角色创建、编辑、删除统一收敛到权限矩阵页面。

## 调用关系

系统管理子页面由后端菜单树和当前用户菜单权限动态注册。
`src/router/index.ts` 只保留根布局，实际业务路由由 RBAC 菜单权限生成。

## 输入

- 后端菜单：`GET /api/system/menus`
- 登录态权限：`GET /api/user/current-permissions`
- 用户操作：用户维护、角色维护、权限配置、模型配置、日志筛选、问答审计筛选

## 输出

- 动态系统管理 Tab
- 权限矩阵角色 CRUD 和菜单/按钮授权
- TDesign Dialog、Drawer、Toast 和 Table 交互反馈

## 示例

系统管理不再使用单独的 `SystemManagementPage` 静态入口。

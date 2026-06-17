# System Management Module

## 功能

提供系统管理页面，覆盖用户管理、角色管理、权限矩阵、部门管理、操作日志和问答审计。

## 调用关系

`src/router/index.tsx` 挂载 `SystemManagementPage` 到 `/system`。页面读取项目列表用于用户项目分配，其余系统管理数据使用本地 Mock 状态维护。

## 输入

- Store：`projects`
- 用户操作：新增、编辑、禁用、删除、重置密码、分配角色、分配项目、配置权限、日志筛选

## 输出

- 本地 Mock 系统管理状态
- TDesign Dialog、Drawer、Toast 和 Table 交互反馈

## 示例

```tsx
<SystemManagementPage />
```

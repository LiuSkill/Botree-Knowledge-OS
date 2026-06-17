# Pages Module

## 功能

存放路由页面模块说明文档。当前页面包含 Dashboard、知识中心、项目中心、审核中心、知识授权中心、AI 中心和系统管理页面。

## 调用关系

路由模块 `frontend/src/router/index.ts` 挂载 `frontend/src/views` 下的 Vue 页面组件。页面通过 API Client、Pinia Store 和 TDesign Vue 组件完成数据读取、权限控制和交互。

## 输入

- 路由参数和查询参数。
- 后端 API 响应数据。
- 当前用户信息和 `permission_codes`。
- 页面本地表单状态。

## 输出

- 路由级 Vue 页面。
- 弹窗、表格、筛选器和操作结果提示。

## 示例

```vue
<KnowledgeBaseListPage />
```

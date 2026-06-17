# Knowledge Authorization Module

## 功能

提供“项目继承企业专业知识”的授权中心，支持按项目配置专业知识分类、密级规则、外部可见范围、授权有效期和权限预览。

## 调用关系

`src/router/index.tsx` 挂载 `KnowledgeAuthorizationPage` 到 `/authorization`。页面通过 Zustand `useAppStore` 读取项目列表与授权配置，并调用授权配置增删改 action。

## 输入

- URL Query：`projectId`
- Store：`projects`、`authorizationConfigs`、`currentUser`
- 用户操作：项目选择、分类勾选、有效期设置、外部可见切换、撤销授权

## 输出

- 更新后的前端 Mock 授权配置
- 授权保存、审批提交、撤销、预览等 TDesign Toast 与 Drawer 反馈

## 示例

```tsx
<KnowledgeAuthorizationPage />
```

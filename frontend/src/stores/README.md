# Stores Module

## 功能

存放 Pinia 状态管理模块。

## 模块清单

- `stores/auth.ts`：当前用户、授权菜单、登录态与权限判断（`useAuthStore`）。
- `stores/locale.ts`：界面语言偏好（`useLocaleStore`）。
- `stores/actionMask.ts`：全局操作遮罩状态。
- `stores/chatRun.ts`：AI 问答运行期状态。

## 调用关系

页面、布局和组件通过 Store Hook 读取或更新全局状态。

## 输入

组件交互事件与异步业务结果。

## 输出

可订阅的前端状态与状态更新方法。

## 示例

```ts
const authStore = useAuthStore();
const hasAccess = authStore.hasMenuPermission('knowledge:view');
```

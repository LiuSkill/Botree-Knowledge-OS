# Stores Module

## 功能

存放 Zustand 状态管理模块。

## 调用关系

页面、布局和组件通过 Store Hook 读取或更新全局状态。

## 输入

组件交互事件与异步业务结果。

## 输出

可订阅的前端状态与状态更新方法。

## 示例

```ts
const sidebarCollapsed = useAppStore((state) => state.sidebarCollapsed);
```

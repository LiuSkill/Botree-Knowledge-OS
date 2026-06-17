# Router Module

## 功能

集中维护 React Router v6 路由配置。

## 调用关系

`App` 组件读取本模块导出的路由表并交给 `useRoutes` 渲染。

## 输入

路由常量、布局组件和页面组件。

## 输出

React Router v6 `RouteObject` 配置数组。

## 示例

```ts
import { routes } from '@/router';
```

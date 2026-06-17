# Mocks Module

## 功能

存放前端离线开发阶段使用的初始化 Mock 数据。

## 调用关系

`stores/appStore.ts` 读取本模块数据并交给 Zustand 管理。

## 输入

领域模型类型与静态 Mock 业务数据。

## 输出

当前用户、知识文档、项目、项目资料、项目成员、授权配置和 AI 会话初始化数据。

## 示例

```ts
import { mockProjects } from '@/mocks/mockData';
```

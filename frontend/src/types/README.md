# Types Module

## 功能

集中维护前端领域模型类型，约束 Store、Mock 数据和页面组件的数据结构。

## 调用关系

`mocks` 和 `stores` 引用本模块类型，页面组件通过 Store 间接获得类型安全的数据。

## 输入

业务字段定义与前端展示所需扩展字段。

## 输出

TypeScript 类型、联合类型和接口。

## 示例

```ts
import type { KnowledgeDocument } from '@/types/domain';
```

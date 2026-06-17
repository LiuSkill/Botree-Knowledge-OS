# Config Module

## 功能

集中维护前端运行时配置与环境变量读取逻辑。

## 调用关系

入口、布局、服务层或业务模块通过配置模块读取标准化配置。

## 输入

`import.meta.env` 注入的 Vite 环境变量。

## 输出

类型安全的配置对象。

## 示例

```ts
import { appConfig } from '@/config/appConfig';
```

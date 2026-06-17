# Shared Module

## 功能

存放跨模块共享的常量、工具类型与纯函数。

## 调用关系

布局、页面、服务和状态模块按需引用共享模块。

## 输入

稳定的业务或工程约定。

## 输出

可复用、类型安全的共享定义。

## 示例

```ts
import { ROUTE_PATHS } from '@/shared/constants/routes';
```

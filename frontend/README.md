# Botree Knowledge OS Frontend

## 功能

前端基于 Vue 3、TypeScript、Vite 和 TDesign Vue Next，实现企业级蓝白风格后台界面。核心页面接入后端真实 API，支持登录、工作台、知识中心、项目中心、知识授权中心、审核中心、AI 中心项目问答、AI 中心基础问答和系统管理。

## 调用关系

`src/main.ts` 负责应用挂载；`src/App.vue` 负责根组件；`src/router` 维护路由和登录守卫；`src/layouts` 提供顶部栏与侧边栏；`src/api` 封装后端接口；`src/stores/auth.ts` 维护登录状态；`src/views` 承载业务页面。

## 输入

- `VITE_API_BASE_URL`：后端 API 地址，开发默认走 Vite 代理 `/api`。
- 用户操作：登录、创建项目、上传文件、审核、解析索引、项目问答、基础问答。
- 后端接口：统一返回 `{ code, message, data }`。

## 输出

- `npm run dev`：启动本地开发服务，默认访问 `http://127.0.0.1:5173`。
- `npm run build`：生成生产构建产物到 `dist`。
- 页面展示：项目问答、基础问答、引用来源、Agent 执行过程、操作日志、问答审计。

## 示例

```bash
npm install
npm run dev
npm run build
```

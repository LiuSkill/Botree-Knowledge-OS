# Botree Agent / Botree Knowledge OS MVP

Botree Agent 是企业内部知识管理与智能体应用平台 MVP，已打通知识资料从上传、审核、解析、分块、索引到 AI 问答引用追溯的核心闭环。

## 1. 项目目录结构

```text
backend/
  app/
    api/              FastAPI Controller 层
    services/         业务服务层
    repositories/     数据访问层
    models/           SQLAlchemy ORM 模型
    schemas/          Pydantic 请求与响应模型
    knowledge/        上传、解析、分块、索引模块
    retrieval/        检索路由与检索器
    agent/            Agent 规划与回答生成
    core/             配置、数据库、安全、异常
  tests/              MVP 主流程烟测
frontend/
  src/
    api/              前端 API 客户端
    views/            Vue 业务页面
    layouts/          顶部栏与侧边栏布局
    components/       通用业务组件
    stores/           登录状态
docs/database/        数据库设计文档
scripts/init_mysql.sql MySQL 初始化脚本
```

## 2. 已实现页面清单

- 登录页：`/login`
- 首页工作台：`/dashboard`
- 知识中心：`/knowledge`
- 知识库详情：`/knowledge/bases/:id`
- 文档详情与 Chunk 查看：`/documents/:id`
- 项目中心：`/projects`
- 项目详情：`/projects/:id`
- 知识授权中心：`/authorization`
- 审核中心：`/reviews`
- 审核详情：`/reviews/:id`
- AI 中心-项目问答：`/ai/project-chat`
- AI 中心-基础问答：`/ai/base-chat`
- 系统管理：用户、角色、权限矩阵、模型配置、操作日志、问答审计

## 3. 已实现接口清单

- 认证：`POST /api/auth/login`、`GET /api/auth/me`、`POST /api/auth/logout`
- 用户角色：`/api/users`、`/api/roles`、`/api/roles/permissions/matrix`
- 项目：`/api/projects`、`/api/projects/{id}`、`/api/projects/{id}/members`
- 知识库：`/api/knowledge-bases`、`/api/knowledge-bases/{id}`、上传与授权摘要
- 文档：列表、详情、下载信息、提交审核、解析、索引、版本、指定版本文件查看/下载、归档、Chunk 查看
- 审核：`/api/review-tasks`、通过、驳回、文档审核日志
- 检索：`POST /api/retrieval/search`
- AI 问答：按 `chat_type` 区分项目问答和基础问答，会话、消息、`POST /api/chat/completions`
- 系统管理：仪表盘、操作日志、问答审计、模型配置、健康检查

## 4. 数据库表清单

核心表包括：`users`、`roles`、`permissions`、`projects`、`project_members`、`knowledge_bases`、`knowledge_base_permissions`、`documents`、`document_versions`、`document_chunks`、`review_tasks`、`review_logs`、`chat_sessions`、`chat_messages`、`chat_citations`、`model_configs`、`operation_logs`、`system_configs`、`graph_entities`、`graph_relations`。

完整设计见 [docs/database/database_design.md](docs/database/database_design.md)，初始化脚本见 [scripts/init_mysql.sql](scripts/init_mysql.sql)。

## 5. 启动方式

后端：

```bash
cd backend
python -m pip install -r requirements.txt
python -m uvicorn main:app --host 0.0.0.0 --port 8888
```

前端：

```bash
cd frontend
npm install
npm run dev
```

访问地址：

- 后端 API：http://127.0.0.1:8888
- 前端页面：http://127.0.0.1:5173
- Swagger：http://127.0.0.1:8888/docs

## 6. 默认账号

- 用户名：`admin`
- 密码：`admin123456`

## 7. 自测结果

已通过：

- `python -m compileall backend`
- `cd backend && python tests/smoke_test.py`
- `cd frontend && npm run build`

烟测覆盖：登录、创建项目、上传项目资料、项目问答未选项目拦截、未审核问答不引用、提交审核、审核通过、解析、索引、项目问答和基础问答返回引用来源、问答审计记录。

## 8. 当前简化实现

- MVP 检索使用数据库关键词检索和结构化过滤，Milvus、知识图谱、网页搜索已预留模块边界。
- 文档解析优先使用本地文本、PDF、DOCX 解析；MinerU 配置已接入，后续可替换为真实解析服务调用。
- AI 回答当前使用可追溯证据摘要生成，模型配置已接入，后续可替换为真实 LLM 调用。
- 外部用户授权保留数据结构和展示入口，细粒度授权编辑可在后续迭代完善。

## 9. 后续开发建议

- 接入真实 MinerU 解析队列和异步任务状态。
- 接入 Embedding 模型与 Milvus，实现向量和关键词混合检索。
- 基于 `graph_entities`、`graph_relations` 增加实体抽取和 GraphRAG 检索。
- 增加 Alembic 迁移、生产级权限编辑和更完整的审计报表。
- 增加 Playwright 端到端测试，覆盖前端主要操作链路。

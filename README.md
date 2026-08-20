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

Python 版本要求：`>=3.11,<3.14`（见 `backend/pyproject.toml`；本地开发基于 3.13 验证，Docker 镜像基于 3.11）。

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

## 8. 实现状态与简化边界

- 检索已接入 PageIndex、ripgrep、Milvus 向量、知识图谱与视觉索引等多路检索，经融合/重排与权限回查后输出证据；主要实现见 `backend/app/retrieval/` 与 `backend/app/langgraph/retrieval_graph.py`。
- 文档解析支持本地文本/PDF/DOCX 与 MinerU 服务两种链路，Office 文档经 LibreOffice 转 PDF 后解析；MinerU 任务队列与异步状态已接入 RQ Worker。
- AI 回答已接入真实 LLM（OpenAI-compatible / DashScope）与视觉模型，回答必须基于检索证据并携带可追溯引用；未配置真实模型时接口明确报错，不生成假回答或假索引。
- 知识授权保留数据结构和授权摘要入口，细粒度授权编辑（原 `knowledge_base_permissions`）尚未形成管理闭环。

## 9. 后续开发建议

- 完善知识授权细粒度编辑闭环（当前仅摘要展示）。
- 启用召回门禁（`RUNTIME_RECALL_GATE_ENABLED`）作为检索质量常态化门槛，并补充生产环境漂移监测。
- 增加 Playwright 端到端测试与前端组件级测试，覆盖前端主要操作链路。
- 规范化生产部署：启动建库与 Alembic 迁移解耦、统一日志落盘与轮转、常驻进程与备份恢复演练。

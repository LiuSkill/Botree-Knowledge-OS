# Botree Knowledge OS 架构清单

> 基线日期：2026-07-24  
> 基线范围：当前工作区（包含未提交修改），覆盖 `frontend/`、`backend/`、`eval/`、`deploy/`、数据库迁移与运行配置。  
> 判定原则：以可达入口和实际调用链为主；已有文档仅作辅助证据。本文不评价未来理想架构。

## 1. 总体定位

系统是一个前后端分离的企业后台应用，将企业知识与项目知识的采集、版本治理、审核、解析、索引、检索问答和审计串成闭环，并在同一产品中提供工艺主数据、工艺路线及快速财务测算。

```text
Browser / Vue SPA
        |
        v
Nginx / FastAPI API
        |
        +--> Service --> Repository --> MySQL
        |                    |
        |                    +--> Alembic schema
        |
        +--> RQ Worker --> parsing / indexing / publishing / cleanup
        |
        +--> MinIO / local files / MinerU / LibreOffice
        |
        +--> RetrievalGraph --> PageIndex / ripgrep / keyword / Milvus / GraphRAG
        |                          |
        |                          +--> Embedding / Reranker / LLM / Vision model service
        |
        +--> retrieval traces / operation logs / QA audit / redaction audit
```

## 2. 可运行单元

| 单元 | 职责 | 入口与证据 | 状态 |
| --- | --- | --- | --- |
| Vue SPA | 页面、动态菜单路由、操作权限、文档预览、聊天流式交互 | `frontend/src/main.ts`、`frontend/src/router/index.ts`、`frontend/src/router/dynamicRoutes.ts` | 已实现 |
| FastAPI API | REST 接口、JWT/RBAC、业务编排、统一异常和审计上下文 | `backend/main.py`、`backend/app/api/` | 已实现 |
| RQ Worker | 文档解析、索引构建、索引发布、外部资源清理 | `backend/worker.py`、`backend/app/tasks/index_tasks.py` | 已实现；依赖 Redis 和外部设施 |
| Model Service | 独立承载 Embedding 与 Reranker 推理，支持启动预热 | `backend/app/model_service/main.py`、`deploy/scripts/02_start_model_service.sh` | 已实现；生产可用性待部署确认 |
| BEIR 评测工具 | 对多种检索/RAG 适配器执行离线评测和报告生成 | `eval/beir/`、`eval/beir/README.md` | 已实现；不属于在线产品入口 |
| 部署脚本集 | 创建目录、启动中间件/API/Worker/模型服务、发布前端、健康检查和备份 | `deploy/scripts/`、`deploy/README.md` | 已实现；目标 Linux/Docker 环境待现场确认 |

## 3. 前端架构

### 3.1 结构

| 层次 | 位置 | 责任 |
| --- | --- | --- |
| 应用入口 | `frontend/src/main.ts` | 注册 Pinia、Vue Router、TDesign、Chat 组件与权限指令 |
| 路由与权限 | `frontend/src/router/` | 登录守卫；根据后端授权菜单树动态注册页面和详情子路由 |
| 页面 | `frontend/src/views/` | 按知识、项目、审核、问答、工艺、系统管理组织业务页面 |
| API 客户端 | `frontend/src/api/` | 封装后端接口和流式问答 |
| 状态 | `frontend/src/stores/` | 当前用户、授权菜单、全局 UI 状态；业务页面主要从真实 API 取数 |
| 通用组件 | `frontend/src/components/` | 布局、上传、状态、文档放大预览、引用、富文本与 Agent 轨迹 |
| 权限常量 | `frontend/src/constants/permissions.ts` | 菜单权限与按钮级操作权限清单 |

### 3.2 路由策略

- `/login`、工艺路线预览和独立财务计算器是静态路由。
- 登录后先通过 `/api/auth/me` 获取用户与授权菜单，再由 `syncAuthorizedRoutes()` 注入业务路由。
- 菜单权限控制页面是否可达，`v-permission` 和操作权限编码控制按钮动作。
- 详情路由随其上级菜单权限注册，避免仅隐藏菜单但仍可直接访问页面。
- 证据：`frontend/src/router/index.ts`、`frontend/src/router/dynamicRoutes.ts`、`frontend/src/directives/permission.ts`。

### 3.3 已知边界

- `frontend/src/mocks/` 与 `frontend/src/stores/appStore.ts` 是早期 Mock 体系；当前只发现国际化工具仍引用 `useAppStore`，主要业务页面未使用这些 Mock 数据，属于遗留代码而非产品数据源。
- 未发现 `*.spec.*` 或 `*.test.*` 前端测试文件，前端质量门主要依赖 `vue-tsc` 和 Vite 构建。

## 4. 后端架构

### 4.1 分层

| 层次 | 位置 | 责任与边界 |
| --- | --- | --- |
| Controller | `backend/app/api/` | 路由、Schema、鉴权依赖、Service 调用和统一响应 |
| Service | `backend/app/services/` | 状态流转、权限规则、事务和跨存储业务编排 |
| Repository | `backend/app/repositories/` | SQLAlchemy 查询、持久化和聚合读取 |
| Database Model | `backend/app/models/` | ORM 实体及关系 |
| Knowledge Pipeline | `backend/app/knowledge/` | 上传、解析、清洗、分块、索引适配器 |
| Retrieval | `backend/app/retrieval/` | 多检索器、融合、重排前路由和范围归一化 |
| Agent/RAG | `backend/app/agent/`、`backend/app/langgraph/` | 问题理解、策略、检索执行、证据判断、回答与降级 |
| Core | `backend/app/core/` | 环境配置、数据库、Redis、MinIO、Milvus、JWT、RBAC、密级和异常 |

后端整体符合 `Controller -> Service -> Repository -> Database`；文件、向量、图谱和模型调用由 Service/Pipeline 通过适配边界协调。

### 4.2 API 模块

FastAPI 在 `backend/main.py` 注册以下前缀：`/api/auth`、`/users`、`/user`、`/roles`、`/projects`、`/knowledge-bases`、`/knowledge-categories`、`/documents`、`/review-tasks`、`/retrieval`、`/chat`、`/model-configs`、`/process-config`、`/system`、`/system/departments`、`/sensitive-content` 和健康检查。

### 4.3 数据域

| 数据域 | 主要表/模型 | 说明 |
| --- | --- | --- |
| 身份权限 | `users`、`roles`、`permissions`、`departments` | 用户、角色、菜单/操作权限与部门树 |
| 项目 | `projects`、`project_members` | 项目基本信息、密级与成员范围 |
| 知识 | `knowledge_bases`、`knowledge_categories` | 企业/项目知识库和分类树 |
| 文档 | `documents`、`document_versions`、`document_chunks`、`document_assets` | 文档主记录、版本、证据分块和派生资产 |
| 页索引 | `document_pages`、`document_page_blocks`、`page_indexes` | 页级解析、块和 staging/published/obsolete 索引 |
| 审核与任务 | `review_tasks`、`review_logs`、`index_tasks` | 版本审核与离线任务状态 |
| 问答审计 | `chat_sessions`、`chat_messages`、`chat_citations`、`retrieval_traces` | 会话、消息、真实引用和检索轨迹 |
| 图谱 | `graph_entities`、`graph_relations` | MySQL 内的版本化实体关系索引 |
| 系统治理 | `model_configs`、`operation_logs`、`system_configs` | 模型路由、操作审计和系统配置 |
| 敏感治理 | `sensitive_type`、`sensitive_filter_rule`、`role_sensitive_permission`、`sensitive_redaction_audit` | 规则、角色策略和脱敏审计 |
| 工艺配置 | `process_*` 系列表 | 基础库、节点投入产出、路线、版本和导入批次 |

当前共有 18 个 Alembic 迁移文件；表清单以 ORM 与迁移为现状依据，`docs/database/database_design.md` 中仍有部分“预留”措辞已落后于当前 GraphRAG 实现。

## 5. 核心业务链路

### 5.1 项目创建

`POST /api/projects` -> `ProjectService.create_project()` -> 创建项目、创建者成员关系、项目知识库及默认分类/目录。访问时再叠加 RBAC、项目成员范围和密级校验。

证据：`backend/app/api/projects.py`、`backend/app/services/project_service.py`、`backend/app/services/project_access_service.py`。

### 5.2 文档生命周期

```text
上传 -> 文档 + V1 草稿 -> 解析任务
     -> 提交具体版本审核 -> 通过 / 驳回
     -> 解析 / 质检 -> 索引构建(staging)
     -> 发布索引 -> 新版本生效、旧索引 obsolete
     -> 在线检索
```

关键规则：

- 新版本不会仅因上传而替换生效版本。
- 审核任务绑定具体版本；驳回必须记录理由，可修订后再提审。
- 索引发布成功才切换生效版本；失败时旧版本继续可检索。
- 删除文档同步清理关系数据，并通过后台任务清理对象存储和向量索引。
- 证据：`backend/app/services/document_service.py`、`review_service.py`、`index_pipeline_service.py`、`index_task_service.py`。

### 5.3 Agentic RAG

```text
chat completion
 -> policy / question understanding
 -> retrieval planner
 -> planned parallel retrieval
 -> access guard + merge + rerank
 -> evidence judge / retry
 -> answer policy gate
 -> answer + citations + trace
```

- 在线检索器包括 `project_metadata`、`page_index`、`milvus`、`ripgrep`、`keyword`、`graphrag`。
- `project_chat` 必须指定项目并执行项目访问、版本、审核、索引和密级二次校验。
- `base_chat` 以企业知识为主；无证据时通过显式确认才进入通用知识回答。
- 项目元数据为 `metadata_only`，不能替代真实文档证据或生成持久化引用。
- 引用必须落到有效知识库、文档、版本/分块/页码；检索全过程可写入 `retrieval_traces`。
- 证据：`backend/app/langgraph/retrieval_graph.py`、`backend/app/retrieval/router.py`、`backend/app/services/chat_service.py`、`answer_policy_gate_service.py`。

### 5.4 工艺配置与测算

基础库 -> 工艺节点投入/消耗/设备/人员/产出 -> 工艺路线编排及版本 -> 区域价格与产出系数 -> 快速财务测算。Excel 导入/导出由独立 Service 处理并记录导入批次。

证据：`backend/app/api/process_config.py`、`backend/app/services/process_config_service.py`、`process_config_excel_service.py`、`process_calculator_service.py`。

## 6. 跨域约束

| 约束 | 实现 |
| --- | --- |
| 身份认证 | JWT；当前用户由 API 依赖解析，禁用用户不能继续登录 |
| RBAC | 后端权限编码 + 前端动态菜单/操作指令双层控制 |
| 数据范围 | 角色数据范围、部门和项目成员关系共同过滤 |
| 三级密级 | 项目、文档、分块和证据沿链路继承并在查询/检索时校验 |
| 审核门禁 | 未审核通过或未发布索引的内容不能作为在线问答正文证据 |
| 敏感内容 | 类型/规则/角色策略驱动放行、掩码或阻断，并记录脱敏审计 |
| 可观测性 | 操作日志、问答审计、检索轨迹、任务进度；进程日志输出到标准输出 |
| 配置安全 | 数据库、存储、模型和密钥由环境变量/模型配置管理，代码禁用 mock/fallback 模型供应商 |

## 7. 外部设施与降级边界

| 设施 | 用途 | 静态判定 |
| --- | --- | --- |
| MySQL | 核心关系数据 | 已集成；开发可配置 SQLite 回退，正式部署使用 MySQL |
| Redis + RQ | 异步解析、索引、发布、清理 | 已集成；无 Redis 时异步闭环不可用 |
| MinIO | 原始文件、派生资产、头像 | 已集成；部分文件流程可退回本地路径，头像要求对象存储 |
| Milvus | 向量索引与语义检索 | 已集成；真实可用性依赖服务和 Embedding 维度一致 |
| MinerU | 复杂文档解析 | 已集成；未配置时简单格式走本地解析，复杂格式能力受限 |
| LibreOffice | Office 转 PDF | 已集成；依赖运行环境中的 `soffice` |
| LLM/Vision | 问题理解、证据判断、回答和视觉处理 | 已集成；缺少真实配置会明确失败，不生成假结果 |
| Model Service | Embedding/Reranker 独立推理 | 可选部署；默认可由本地或其他真实 provider 替代 |

## 8. 质量与运维基线

- 后端现有 57 个 `test_*.py` 文件、362 个测试函数，重点覆盖文档、检索规划、Agent 策略、解析、模型路由、敏感内容和工艺测算。
- 前端没有自动化测试；构建脚本为 `tsc -b && vite build`。
- 部署脚本包含中间件启动、Alembic 升级、API/Worker/模型服务、Nginx、健康检查、MySQL 备份和文件备份。
- API、Worker 与模型服务的生产拓扑已有脚本，但真实容量、GPU、备份恢复演练、日志采集和告警效果属于待确认环境事实。

## 9. 架构状态清单

### 已实现

- Vue 动态 RBAC SPA 与 FastAPI 分层 API。
- 企业/项目双知识域、项目成员和三级密级。
- 文档版本审核、解析、页/块、异步索引与发布切换。
- 六路检索、融合/重排、证据判断、引用与轨迹审计。
- 工艺基础库、节点、路线、版本、Excel 导入导出和财务测算。
- 敏感内容规则、角色策略与审计。
- MySQL/Redis/MinIO/Milvus/模型服务的部署脚本。

### 部分实现

- 知识授权：后端/数据结构和只读摘要存在，但缺少完整授权编辑产品闭环。
- 前端质量体系：类型构建存在，缺少组件与 E2E 自动化测试。
- 可观测性：数据库审计充分，进程日志、指标、集中告警和链路平台未形成完整闭环。
- 遗留前端 Mock Store 仍在仓库中，与真实 API 架构并存。

### 仅有设计或历史描述

- `knowledge_base_permissions` 的细粒度用户/角色/项目/外部用户授权仍主要见数据库设计说明和授权中心占位文案。
- README 中“Milvus、图谱仅预留”“回答为证据摘要”的描述属于旧阶段，不能代表当前代码。

### 待确认

- 当前部署环境中 MySQL、Redis、MinIO、Milvus、MinerU、LibreOffice、LLM、GPU 模型服务的实际连通性与容量。
- Linux/Docker 部署脚本是否已在目标机器完整演练，包括备份恢复和故障切换。
- 真实数据规模下六路检索的延迟、召回质量和成本指标。

## 10. 主要证据索引

- 运行入口：`backend/main.py`、`backend/worker.py`、`frontend/src/main.ts`
- API：`backend/app/api/`
- 分层：`backend/app/services/`、`backend/app/repositories/`、`backend/app/models/`
- 文档链路：`backend/app/services/document_service.py`、`review_service.py`、`index_pipeline_service.py`
- RAG：`backend/app/langgraph/retrieval_graph.py`、`backend/app/retrieval/router.py`
- 前端功能入口：`frontend/src/router/dynamicRoutes.ts`、`frontend/src/constants/permissions.ts`
- 数据演进：`backend/alembic/versions/`
- 部署：`deploy/`
- 测试：`backend/tests/`

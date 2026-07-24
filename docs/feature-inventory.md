# Botree Knowledge OS 功能清单

> 基线日期：2026-07-24  
> 口径：以用户可感知的业务能力为一级条目，并追溯页面、API、Service、模型或测试。  
> 状态：**已实现**＝存在可达入口与完整执行链路；**部分实现**＝链路未闭环；**仅设计**＝只有文档/占位；**待确认**＝代码存在但依赖真实环境验证。

## 1. 产品入口总览

| 业务域 | 主要页面 | 后端入口 | 总体状态 |
| --- | --- | --- | --- |
| 认证与个人资料 | `/login`、全局头像/密码入口 | `/api/auth`、`/api/user` | 已实现 |
| 首页工作台 | `/dashboard` | `/api/system/dashboard` | 已实现 |
| 企业知识 | `/knowledge`、`/knowledge/bases/:id` | `/api/knowledge-bases`、`/knowledge-categories` | 已实现 |
| 文档治理 | `/documents/:id` | `/api/documents` | 已实现 |
| 项目中心 | `/projects`、`/projects/:id`、项目资料管理 | `/api/projects` | 已实现 |
| 知识授权 | `/authorization` | `/api/knowledge-bases/authorization-summary` | 部分实现 |
| 审核中心 | `/reviews`、`/reviews/:id` | `/api/review-tasks`、文档审核日志 | 已实现 |
| 知识问答 | `/ai/base-chat`、`/ai/project-chat` | `/api/chat`、项目问答接口 | 已实现；模型环境待确认 |
| 工艺配置 | `/process-config/*` | `/api/process-config` | 已实现 |
| 系统治理 | `/system/*` | 用户、部门、角色、模型、日志、审计、敏感内容 API | 已实现 |

## 2. 认证、用户与权限

| 能力 | 状态 | 实现与业务规则 | 证据 |
| --- | --- | --- | --- |
| 用户名密码登录/退出 | 已实现 | 校验账号启用状态，签发 JWT；登录后加载当前用户、角色和权限 | `backend/app/api/auth.py`、`auth_service.py`、`frontend/src/views/login/LoginPage.vue` |
| 当前用户资料 | 已实现 | 获取个人资料，上传/删除头像，修改密码 | `backend/app/api/auth.py`、`user_service.py` |
| 用户管理 | 已实现 | 列表、分页、部门筛选、创建、详情、编辑、软删除、重置密码 | `backend/app/api/users.py`、`user_service.py`、`UserManagePage.vue` |
| 部门管理 | 已实现 | 部门树、负责人候选、创建、编辑、启停和删除校验 | `backend/app/api/departments.py`、`department_service.py`、`DepartmentManagePage.vue` |
| 角色管理 | 已实现 | 角色 CRUD、启用状态、密级和数据范围 | `backend/app/api/roles.py`、`RoleService`、`PermissionMatrixPage.vue` |
| 菜单与操作权限 | 已实现 | 后端返回授权菜单；前端动态注册路由并控制按钮；权限矩阵可维护角色权限 | `backend/app/api/system.py`、`frontend/src/router/dynamicRoutes.ts`、`constants/permissions.ts` |
| 项目数据范围 | 已实现 | 项目成员、角色范围、部门范围及项目操作权限共同决定访问 | `project_access_service.py`、`core/data_scope.py` |
| 三级密级 | 已实现 | 项目/文档/分块/证据受用户最高密级过滤 | `core/security_levels.py`、`evidence_access_guard_service.py`、相关测试 |

## 3. 首页工作台

| 能力 | 状态 | 实现与业务规则 | 证据 |
| --- | --- | --- | --- |
| 业务统计 | 已实现 | 文档、知识条目、项目、问答等统计按用户数据范围返回 | `backend/app/api/system.py`、`system_service.py`、`DashboardPage.vue` |
| 趋势与分布 | 已实现 | QA 趋势、文档类型/知识资产分布等数据接口和图表 | `system_service.py`、`test_dashboard_*.py` |
| 最近事项和快捷入口 | 已实现 | 最近资料、项目、问答、待审事项及模块跳转 | `DashboardPage.vue`、`frontend/src/api/system.ts` |

## 4. 企业知识与知识库

| 能力 | 状态 | 实现与业务规则 | 证据 |
| --- | --- | --- | --- |
| 企业/项目知识库 | 已实现 | 知识库区分企业与项目类型；项目创建时自动建立项目知识库 | `knowledge_base_service.py`、`project_service.py`、`models/knowledge_base.py` |
| 知识库 CRUD | 已实现 | 列表、详情、创建、编辑、删除，返回文档/分块统计 | `backend/app/api/knowledge_bases.py`、`knowledge_base_service.py` |
| 知识分类树 | 已实现 | 多级分类的查询、创建、编辑和删除；有关联子类/文档时阻止删除 | `knowledge_categories.py`、`knowledge_category_service.py` |
| 知识文档列表 | 已实现 | 搜索、类型/状态/分类筛选、分页和权限过滤 | `KnowledgeBaseListPage.vue`、`KnowledgeCollectionPage.vue`、`documents.py` |
| 上传与提审 | 已实现 | 上传到指定知识库和分类，生成文档与 V1 草稿，可提交审核 | `knowledge_bases.py`、`document_service.py`、上传页面 |
| 授权摘要 | 已实现 | 展示当前可见知识库及授权边界摘要 | `knowledge_bases.py`、`KnowledgeAuthPage.vue` |
| 细粒度知识授权编辑 | 仅设计 | `knowledge_base_permissions` 和外部用户授权在设计/页面文案中预留，未形成管理 API + 页面闭环 | `docs/database/database_design.md`、`KnowledgeAuthPage.vue` |

## 5. 项目中心

| 能力 | 状态 | 实现与业务规则 | 证据 |
| --- | --- | --- | --- |
| 项目列表和 CRUD | 已实现 | 按用户范围查询；项目编码唯一；支持创建、详情、编辑和删除 | `backend/app/api/projects.py`、`project_service.py`、`ProjectListPage.vue` |
| 项目自动初始化 | 已实现 | 创建项目时建立创建者成员关系、项目知识库和默认分类/目录 | `ProjectService.create_project()`、项目流程测试 |
| 项目概览 | 已实现 | 汇总基本信息、知识库、目录、文档、成员和统计 | `/api/projects/{id}/overview`、`ProjectDetailPage.vue` |
| 项目资料目录 | 已实现 | 目录树查询、增删改和模板初始化；删除受关联资料约束 | `projects.py`、`project_directory_import_service.py`、项目页面 |
| 项目成员 | 已实现 | 后端支持列表、添加和移除；当前项目详情页面已有成员展示 | `projects.py`、`project_service.py`、`ProjectDetailPage.vue` |
| 项目成员前端维护 | 部分实现 | 后端链路完整，但静态页面盘点未确认与新增/移除接口等量的操作入口 | `frontend/src/views/project/`、`frontend/src/api/projects.ts` |
| 项目资料管理 | 已实现 | 分页、上传、编辑元数据、删除、发布、重试解析/索引、密级和版本管理 | `projects.py`、`ProjectDocumentManagePage.vue` |
| 项目目录批量导入 | 已实现 | 按目录结构导入项目资料，包含去重/映射和独立脚本 | `project_directory_import_service.py`、`scripts/import_project_directory.py`、测试 |
| 项目问答跳转 | 已实现 | 从项目上下文进入项目问答并锁定/选择项目 | `ProjectDetailPage.vue`、`ProjectChatPage.vue` |

## 6. 文档生命周期

| 能力 | 状态 | 实现与业务规则 | 证据 |
| --- | --- | --- | --- |
| 文档上传 | 已实现 | 企业/项目知识均可上传；创建主记录和 V1 草稿，保存原始文件 | `document_service.py`、`UploadService`、相关 API |
| 元数据与密级 | 已实现 | 可编辑名称、分类等元数据；密级不得超过操作者最高密级 | `documents.py`、`DocumentService.update_*`、密级测试 |
| 版本管理 | 已实现 | 上传新版本、版本列表、指定版本下载、设当前、回滚和变更说明 | `documents.py`、`document_service.py`、`DocumentDetailPage.vue` |
| 版本隔离 | 已实现 | 新上传版本不直接替换生效版本；版本独立审核、解析和索引 | `document_service.py`、`test_document_service.py` |
| 审核提交 | 已实现 | 仅草稿/驳回版本可提审；审核任务绑定具体版本 | `review_service.py`、`documents.py` |
| 审核通过/驳回 | 已实现 | 仅 reviewing 任务可处理；驳回理由必填；同步任务、版本和必要的文档主状态 | `review_service.py`、`ReviewDetailPage.vue` |
| 批量审核 | 已实现 | 支持审核任务批量通过和驳回 | `backend/app/api/reviews.py`、`ReviewTaskPage.vue` |
| 文档归档 | 已实现 | 归档后更新文档治理状态并退出正常生效范围 | `documents.py`、`document_service.py` |
| 文档删除与清理 | 已实现 | 清理版本、页/块、图谱、审核、引用、轨迹和任务；外部存储/向量异步清理 | `document_service.py`、删除测试 |

## 7. 解析、预览与索引

| 能力 | 状态 | 实现与业务规则 | 证据 |
| --- | --- | --- | --- |
| 简单文本解析 | 已实现 | TXT/Markdown/CSV 等通过本地解析器形成页级结果 | `knowledge/parsing/simple_text_parser.py`、`parser_service.py` |
| 复杂文档解析 | 已实现；环境待确认 | MinerU 任务提交、轮询、结果和缓存链路存在 | `mineru_parser.py`、`parser_service.py`、解析测试 |
| Office 转 PDF | 已实现；环境待确认 | LibreOffice 转换后进入解析，包含超时和进程树清理 | `libreoffice_conversion_service.py`、解析测试 |
| 内容清洗 | 已实现 | 清洗解析噪声并保留可检索文本结构 | `parsed_content_cleaner.py`、清洗测试 |
| 原始内容预览 | 已实现 | Markdown、转换 PDF、页预览图和块图片；详情/审核页支持放大 | `documents.py`、`DocumentDetailPage.vue`、`ReviewDetailPage.vue`、`ZoomPreviewDialog.vue` |
| 页级质检 | 已实现 | 对解析页面执行质量检查并返回质量结果 | `/documents/{id}/quality-check`、`page_index_service.py` |
| 页级人工修正 | 已实现 | 修改指定页的人工修正内容并更新相应文本 | `/documents/{id}/pages/{page_no}/correction`、`document_service.py` |
| 分块 | 已实现 | 从解析内容构造可引用 Chunk，并保存版本、页码、图号和密级 | `knowledge/chunking/`、`document_chunks` |
| 同步索引构建 | 已实现 | 提供解析、索引、解析并构建等管理接口 | `documents.py`、`index_pipeline_service.py` |
| 异步索引任务 | 已实现 | 单文档/批量构建和发布，含 pending/running/success/failed/canceled 与进度 | `index_task_service.py`、`tasks/index_tasks.py`、审核中心 |
| 原子发布切换 | 已实现 | 新索引 staging 后发布；成功才切换版本，旧索引变 obsolete；失败保留旧版本 | `index_pipeline_service.py`、文档服务测试 |
| Milvus 向量索引 | 已实现；环境待确认 | 真实 Embedding 写入 Milvus；禁用假向量 provider | `knowledge/indexing/milvus_indexer.py`、`embedding_service.py` |
| MySQL 图谱索引 | 已实现 | 从文档内容生成版本化实体关系，支持 staging/published/obsolete | `graph_index_service.py`、`graph_repository.py`、图谱测试 |

## 8. 检索与 AI 问答

| 能力 | 状态 | 实现与业务规则 | 证据 |
| --- | --- | --- | --- |
| 会话管理 | 已实现 | 创建、列表、切换、重命名、置顶、收藏、删除和历史消息 | `chat.py`、`chat_service.py`、`ChatWorkspace.vue` |
| 流式问答 | 已实现 | SSE/流式事件展示理解、规划、检索、筛选和回答阶段 | `/chat/completions/stream`、`chatProgress.ts` |
| 基础问答 | 已实现；模型环境待确认 | 以企业知识为范围；无证据时需用户确认才能使用通用知识 | `BaseChatPage.vue`、`answer_policy_gate_service.py`、`chat_service.py` |
| 项目问答 | 已实现；模型环境待确认 | 必须指定项目；可按配置补充企业知识；强制项目访问和密级校验 | `ProjectChatPage.vue`、`project_access_service.py`、RAG 策略测试 |
| 问题理解与规划 | 已实现 | 规则 + LLM 解析任务类型、知识范围和检索需求，生成检索器计划和降级梯子 | `question_understanding_service.py`、`retrieval_planner_service.py` |
| 多路检索 | 已实现 | ProjectMetadata、PageIndex、Milvus、ripgrep、Keyword、GraphRAG 可按策略并行/分阶段执行 | `retrieval/router.py`、`retrieval/retrievers/` |
| 融合与重排 | 已实现；模型环境待确认 | 合并去重、访问守卫、真实 Reranker 和 Top-K 控制 | `retrieval/merger.py`、`reranker_service.py`、相关测试 |
| 证据判断与重试 | 已实现 | 判断 empty/weak/partial/conflicted/enough，并按预算选择查询和检索器重试 | `retrieval_graph.py`、`evidence_evaluator_service.py` |
| 严格拒答 | 已实现 | 项目知识证据不足时拒绝无依据回答；基础问答遵循 KB-first 确认流程 | `answer_policy_gate_service.py`、策略测试 |
| 视觉证据 | 已实现；视觉模型环境待确认 | 根据页面/图纸/图像信号补充页预览和块资源，可进入多模态判断 | `visual_evidence_service.py`、视觉证据测试 |
| 引用追溯 | 已实现 | 引用落到真实知识库、文档、Chunk/页码/图号；元数据占位证据不持久化 | `chat_service.py`、`chat_citations`、引用测试 |
| 检索轨迹 | 已实现 | 保存意图、子查询、各路命中、重排、引用和耗时；用户和管理员可查看 | `retrieval_trace_service.py`、`AgentTracePanel.vue`、系统审计 API |
| 回答反馈 | 已实现 | 用户可对回答设置反馈状态 | `/chat/messages/{id}/feedback`、`chat_service.py` |

## 9. 工艺配置与快速财务测算

| 能力 | 状态 | 实现与业务规则 | 证据 |
| --- | --- | --- | --- |
| 原料库 | 已实现 | CRUD、启停、区域价格、元素组成、模板、Excel 导入导出 | `process_config.py`、`MaterialLibraryPage.vue`、`process_config_service.py` |
| 产品库 | 已实现 | CRUD、启停、区域价格、模板、Excel 导入导出 | `ProductLibraryPage.vue`、相关 Service/Repository |
| 消耗品库 | 已实现 | CRUD、启停、区域价格、模板、Excel 导入导出 | `ConsumableLibraryPage.vue`、相关 API |
| 公共服务库 | 已实现 | CRUD、启停、区域价格、模板、Excel 导入导出 | `PublicServiceLibraryPage.vue`、相关 API |
| 人员成本库 | 已实现 | CRUD、启停及区域成本配置 | `LaborCostLibraryPage.vue`、`process_config.py` |
| 设备/基础设施资产库 | 已实现 | 共用资产模型，按资产类型展示；CRUD、启停及成本参数 | 对应页面、`ProcessAsset`、`process_config_service.py` |
| 工艺节点库 | 已实现 | 节点 CRUD、输入原料、消耗品、公共服务、设备、人员和产出维护；Excel 导入导出 | `ProcessNodeLibraryPage.vue`、`process_node_*` 模型 |
| 工艺路线库 | 已实现 | 路线 CRUD、节点编排/排序、树形预览、输入原料/最终产品、导入导出 | `ProcessRouteLibraryPage.vue`、`route/detail.vue`、路线 API |
| 路线版本 | 已实现 | 查看和新增路线版本，保存路线快照/说明 | `/routes/{id}/versions`、`ProcessRouteVersion` |
| 测算产出系数 | 已实现 | 维护路线的产品/废物/副产物系数 | `/routes/{id}/calculation-outputs`、`ProcessCalculationOutput` |
| 快速财务测算 | 已实现 | 基于路线、地区、规模和价格执行计算，返回投入产出与财务结果 | `FinancialCalculatorPage.vue`、`process_calculator_service.py`、计算测试 |
| 历史 Excel 计算数据导入 | 已实现 | 导入脚本与批次记录存在，可追踪来源 | `scripts/import_financial_calculator_excel.py`、`ProcessCalculationImportBatch` |

## 10. 审计、模型与敏感内容治理

| 能力 | 状态 | 实现与业务规则 | 证据 |
| --- | --- | --- | --- |
| 操作日志 | 已实现 | 记录关键业务操作、用户、对象及请求上下文，支持分页筛选 | `system_service.py`、`OperationLogPage.vue` |
| QA 审计 | 已实现 | 会话、消息、回答、引用与检索轨迹的关联查询 | `system.py`、`QAAuditPage.vue` |
| 模型配置 | 已实现 | 模型配置 CRUD、启停、连接测试、设置默认与任务模型路由 | `model_configs.py`、`model_service.py`、`ModelConfigPage.vue` |
| 真实模型门禁 | 已实现 | 禁止 fallback/mock/demo provider 生成假回答、假向量或假重排 | `llm_service.py`、`embedding_service.py`、`reranker_service.py` |
| 敏感类型/规则 | 已实现 | 类型和规则 CRUD/启停、规则测试、缓存刷新 | `sensitive_content.py`、`SensitiveContentPage.vue` |
| 角色敏感权限 | 已实现 | 按角色与敏感类型配置放行/掩码/阻断策略 | `RoleSensitivePermissionService`、敏感权限矩阵接口 |
| 表格敏感过滤 | 已实现 | 表格单元格级识别与处理，避免破坏整体表格结构 | `table_sensitive_filter.py`、相关测试 |
| 脱敏审计 | 已实现 | 查询敏感内容命中和处理记录 | `sensitive_content.py`、`SensitiveRedactionAudit` |

## 11. 运维与评测

| 能力 | 状态 | 实现与业务规则 | 证据 |
| --- | --- | --- | --- |
| 数据库迁移 | 已实现 | Alembic 升级纳入 API 启动脚本；当前 18 个迁移 | `backend/alembic/`、`deploy/scripts/03_start_api.sh` |
| 中间件部署 | 已实现；环境待确认 | Docker 启动 MySQL、Redis、MinIO、Milvus 并等待健康 | `deploy/scripts/01_start_middlewares.sh` |
| 应用部署 | 已实现；环境待确认 | 构建镜像、模型服务、API、Worker、前端和 Nginx | `deploy/scripts/02_*` 至 `06_*` |
| 健康检查 | 已实现；环境待确认 | 检查容器、MySQL、Redis、MinIO、Milvus、模型服务、API 和静态站点 | `deploy/scripts/07_health_check.sh` |
| 备份 | 已实现；恢复待确认 | MySQL 压缩备份与文件备份脚本存在；未从仓库确认恢复演练 | `deploy/scripts/08_backup_mysql.sh`、`09_backup_files.sh` |
| 离线检索评测 | 已实现 | BEIR 数据集、索引、适配器、指标和报告写入 | `eval/beir/`、`test_beir_eval.py` |
| 后端自动化测试 | 已实现 | 57 个测试文件、362 个测试函数覆盖关键业务 | `backend/tests/` |
| 前端自动化测试 | 部分实现 | 有类型检查和生产构建，但未发现组件或 E2E 测试 | `frontend/package.json`、前端目录扫描 |

## 12. 迭代基线：明确缺口

### 部分实现

1. 知识授权中心缺少细粒度用户、角色、项目和外部用户授权编辑闭环。
2. 项目成员后端维护能力与前端可操作能力需要通过实际页面验收进一步对齐。
3. 文档质检、页级人工修正等后端能力虽存在，主流程中的产品可发现性仍需验收。
4. 前端缺少自动化测试，关键页面只能依赖构建和人工回归。
5. 进程日志、指标、告警和分布式链路观测尚未形成统一运维产品。

### 仅设计/占位

1. `knowledge_base_permissions` 的完整授权管理流程。
2. 授权中心文案中所述的外部用户授权管理。
3. 仓库中的早期 Mock 业务 Store，不应视为线上功能。

### 待确认

1. 真实部署环境的外部设施、模型、MinerU 和 LibreOffice 连通性。
2. GPU 显存、模型并发、索引吞吐、检索延迟和大数据量分页性能。
3. 部署脚本在目标环境的完整演练、备份恢复、监控和告警。
4. 工艺测算结果是否已经过业务财务口径验收；静态代码只能确认公式链路与测试存在。

## 13. 证据入口

- 页面与菜单：`frontend/src/router/dynamicRoutes.ts`、`frontend/src/constants/permissions.ts`
- 前端 API：`frontend/src/api/`
- 后端路由：`backend/app/api/`
- 业务规则：`backend/app/services/`
- 数据模型：`backend/app/models/`
- 文档处理：`backend/app/knowledge/`
- RAG：`backend/app/langgraph/retrieval_graph.py`、`backend/app/retrieval/`
- 异步任务：`backend/app/tasks/index_tasks.py`、`backend/worker.py`
- 测试：`backend/tests/`
- 部署：`deploy/`

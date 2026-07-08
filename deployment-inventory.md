# 部署调研清单

## 说明

- 本文仅基于当前仓库文件、现有配置文件、SQL 初始化脚本与仓库内文档整理，不包含外部环境实时探测。
- 不能从仓库直接确认的内容统一标记为 `待确认`。
- `backend/.env` 中存在敏感信息；本文只记录“是否已配置”和非敏感地址/端口/路径，不回填真实密钥、密码、JWT 密钥。
- 主要依据文件：`frontend/package.json`、`frontend/vite.config.ts`、`frontend/.env.example`、`frontend/src/api/request.ts`、`frontend/src/api/chat.ts`、`frontend/README.md`、`backend/requirements.txt`、`backend/main.py`、`backend/start.sh`、`backend/worker.py`、`backend/.env.example`、`backend/.env`、`backend/app/core/config.py`、`backend/app/core/database.py`、`backend/app/services/*`、`backend/app/knowledge/*`、`scripts/init_mysql.sql`、`docs/database/database_design.md`。

---

## 1. 前端项目技术栈

| 项目 | 结论 | 依据 |
| --- | --- | --- |
| 前端框架 | Vue 3 + TypeScript | `frontend/package.json`、`frontend/README.md` |
| UI 组件库 | `tdesign-vue-next`、`tdesign-icons-vue-next`、`@tdesign-vue-next/chat` | `frontend/package.json` |
| 构建工具 | Vite 6、`@vitejs/plugin-vue`、TypeScript | `frontend/package.json`、`frontend/vite.config.ts` |
| 本地启动命令 | `cd frontend && npm install && npm run dev` | `frontend/README.md`、`frontend/package.json` |
| 生产构建命令 | `cd frontend && npm run build` | `frontend/README.md`、`frontend/package.json` |
| 构建产物目录 | `frontend/dist` | `frontend/README.md` |
| 前端开发端口 | `5173` | `frontend/vite.config.ts`、`frontend/README.md` |
| API 代理 / 后端地址配置方式 | 优先读取 `VITE_API_BASE_URL`；未配置时回退到 `/api`；开发态通过 Vite 代理将 `/api` 转发到 `http://127.0.0.1:8888` | `frontend/.env.example`、`frontend/vite.config.ts`、`frontend/src/api/request.ts`、`frontend/src/api/chat.ts` |

### `package.json` 主要依赖

- `vue@^3.5.16`
- `vue-router@^4.5.1`
- `pinia@^3.0.3`
- `axios@^1.7.9`
- `@vueuse/core@^13.3.0`
- `tdesign-vue-next@^1.12.0`
- `tdesign-icons-vue-next@^0.3.5`
- `@tdesign-vue-next/chat`（本地 tgz 包）
- `markdown-it@^14.2.0`
- `katex@^0.16.47`

依据：`frontend/package.json`

### 现有后端地址接入方式

1. 环境变量模式：`VITE_API_BASE_URL=http://127.0.0.1:8888/api`  
   依据：`frontend/.env.example`
2. 代码回退模式：`import.meta.env.VITE_API_BASE_URL || '/api'`  
   依据：`frontend/src/api/request.ts`、`frontend/src/api/chat.ts`
3. 开发代理模式：`/api -> http://127.0.0.1:8888`  
   依据：`frontend/vite.config.ts`

---

## 2. 后端项目技术栈

| 项目 | 结论 | 依据 |
| --- | --- | --- |
| Python 版本要求 | `待确认`。仓库未发现 `pyproject.toml`、`.python-version`、`runtime.txt`，`README` 也未声明 Python 版本 | `backend/requirements.txt`、`backend/README.md` |
| Web 框架 | FastAPI | `backend/main.py`、`backend/requirements.txt` |
| ASGI / 本地服务 | Uvicorn | `backend/requirements.txt`、`backend/start.sh`、`backend/README.md` |
| 后端启动入口 | API 入口：`backend/main.py`；异步任务 Worker 入口：`backend/worker.py` | `backend/main.py`、`backend/worker.py` |
| 本地启动命令 | `cd backend && python -m pip install -r requirements.txt && python -m uvicorn main:app --host 0.0.0.0 --port 8888` | `backend/README.md` |
| 现有脚本启动命令 | `cd backend && uvicorn main:app --host 0.0.0.0 --port 8888 --reload` | `backend/start.sh` |
| 生产环境建议启动命令 | API：`cd backend && python -m uvicorn main:app --host 0.0.0.0 --port 8888`；如启用异步索引，还需单独启动 `cd backend && python worker.py` | `backend/README.md`、`backend/worker.py`、`backend/app/services/index_task_service.py` |

### 核心依赖

`backend/requirements.txt` 中与部署最相关的核心依赖包括：

- Web / 配置：`fastapi`、`uvicorn[standard]`、`pydantic`、`pydantic-settings`
- ORM / 数据库：`SQLAlchemy`、`pymysql`、`alembic`
- 认证：`PyJWT`、`python-multipart`
- HTTP：`requests`
- 模型：`sentence-transformers`、`transformers`、`torch`、`accelerate`
- 文件解析：`python-docx`、`pypdf`
- 中间件 / 队列 / 向量库 / 对象存储：`redis`、`rq`、`pymilvus`、`minio`
- Agent / RAG：`langgraph`、`beir`

依据：`backend/requirements.txt`

### 环境变量清单

以下变量由 `backend/app/core/config.py` 的 `Settings` 统一声明：

#### 应用基础

- `APP_NAME`
- `APP_ENV`
- `DEBUG`
- `API_PREFIX`
- `HOST`
- `PORT`

#### 数据库

- `DATABASE_URL`
- `MYSQL_HOST`
- `MYSQL_PORT`
- `MYSQL_DATABASE`
- `MYSQL_USER`
- `MYSQL_PASSWORD`

#### Redis / RQ

- `REDIS_HOST`
- `REDIS_PORT`
- `REDIS_PASSWORD`
- `REDIS_DB`
- `RQ_QUEUE_NAME`

#### MinIO

- `MINIO_ENDPOINT`
- `MINIO_ACCESS_KEY`
- `MINIO_SECRET_KEY`
- `MINIO_BUCKET`
- `MINIO_SECURE`

#### Milvus / 向量

- `MILVUS_HOST`
- `MILVUS_PORT`
- `MILVUS_COLLECTION`
- `EMBEDDING_DIM`

#### MinerU / LibreOffice

- `MINERU_BASE_URL`
- `MINERU_PARSE_PATH`
- `MINERU_TASK_SUBMIT_PATH`
- `MINERU_TASK_TIMEOUT_SECONDS`
- `MINERU_POLL_INTERVAL_SECONDS`
- `MINERU_HTTP_TIMEOUT_SECONDS`
- `MINERU_OUTPUT_HOST_DIR`
- `MINERU_OUTPUT_CONTAINER_DIR`
- `LIBREOFFICE_BINARY`
- `LIBREOFFICE_TIMEOUT_SECONDS`
- `LIBREOFFICE_WORK_DIR`

#### LLM / Vision / Embedding / Reranker

- `OPENAI_COMPATIBLE_BASE_URL`
- `OPENAI_API_KEY`
- `LLM_PROVIDER`
- `LLM_BASE_URL`
- `LLM_API_KEY`
- `LLM_MODEL`
- `LLM_TIMEOUT_SECONDS`
- `INTENT_LLM_MODEL`
- `PLANNER_LLM_MODEL`
- `EVIDENCE_JUDGE_FAST_MODEL`
- `EVIDENCE_JUDGE_MODEL`
- `EVIDENCE_JUDGE_TIMEOUT_SECONDS`
- `ANSWER_LLM_MODEL`
- `ANALYSIS_LLM_MODEL`
- `VISION_LLM_PROVIDER`
- `VISION_LLM_BASE_URL`
- `VISION_LLM_API_KEY`
- `VISION_LLM_MODEL`
- `VISION_LLM_TIMEOUT_SECONDS`
- `VISION_LLM_MAX_IMAGES`
- `VISION_LLM_MAX_IMAGE_BYTES`
- `EMBEDDING_PROVIDER`
- `EMBEDDING_MODEL`
- `EMBEDDING_DEVICE`
- `EMBEDDING_BATCH_SIZE`
- `EMBEDDING_TIMEOUT_SECONDS`
- `RERANKER_DEVICE`
- `RERANKER_BATCH_SIZE`
- `RERANKER_TIMEOUT_SECONDS`

#### 认证 / 默认管理员

- `JWT_SECRET_KEY`
- `JWT_ALGORITHM`
- `ACCESS_TOKEN_EXPIRE_MINUTES`
- `DEFAULT_ADMIN_USERNAME`
- `DEFAULT_ADMIN_PASSWORD`
- `DEFAULT_ADMIN_REAL_NAME`

#### 本地存储 / 检索预算

- `UPLOAD_DIR`
- `PAGE_INDEX_DIR`
- `RIPGREP_BINARY`
- `RIPGREP_TIMEOUT_MS`
- `RETRIEVAL_RETRIEVER_TIMEOUT_MS`
- `RETRIEVAL_MILVUS_TIMEOUT_MS`
- `RETRIEVAL_TOTAL_BUDGET_MS`
- `RETRIEVAL_RETRY_BUDGET_MS`
- `RETRIEVAL_MIN_STAGE_BUDGET_MS`
- `RETRIEVAL_MIN_RETRY_BUDGET_MS`
- `RETRIEVAL_MAX_SUB_QUERIES`
- `RETRIEVAL_MAX_RETRY_QUERIES`
- `RETRIEVAL_MAX_RETRY_RETRIEVERS`
- `RETRIEVAL_PAGE_INDEX_CANDIDATE_LIMIT`
- `RETRIEVAL_PAGE_INDEX_ROW_LIMIT`
- `RETRIEVAL_RIPGREP_CANDIDATE_LIMIT`
- `RETRIEVAL_RIPGREP_ROW_LIMIT`
- `RETRIEVAL_RIPGREP_PATTERN_LIMIT`
- `RETRIEVAL_RIPGREP_MAX_COUNT_PER_FILE`
- `RETRIEVAL_TRACE_ENABLED`
- `PROJECT_CHAT_INCLUDE_INDUSTRY_KNOWLEDGE`

依据：`backend/app/core/config.py`

### 当前 `.env` 中已明确配置的非敏感部署项

- `APP_ENV=development`
- `BACKEND_URL=http://127.0.0.1:8888`
- `FRONTEND_URL=http://127.0.0.1:5173`
- `MYSQL_HOST=127.0.0.1`、`MYSQL_PORT=3306`、`MYSQL_DATABASE=botree_agent`
- `REDIS_HOST=127.0.0.1`、`REDIS_PORT=6379`
- `MINIO_ENDPOINT=127.0.0.1:9000`、`MINIO_BUCKET=graphrag-documents`
- `MILVUS_HOST=127.0.0.1`、`MILVUS_PORT=19530`、`MILVUS_COLLECTION=botree_collection`
- `MINERU_BASE_URL=http://127.0.0.1:8000`
- `MINERU_OUTPUT_HOST_DIR=\\\\wsl.localhost\\Ubuntu\\data\\mineru\\output`
- `MINERU_OUTPUT_CONTAINER_DIR=/workspace/output`
- `LIBREOFFICE_BINARY=C:/Program Files/LibreOffice/program/soffice.exe`
- `OPENAI_COMPATIBLE_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1`
- `LLM_PROVIDER=qwen_api`
- `LLM_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1`
- `LLM_MODEL=qwen3.7-max`
- `VISION_LLM_PROVIDER=qwen_api`
- `VISION_LLM_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1`
- `VISION_LLM_MODEL=qwen3.5-plus`
- `VISION_LLM_MAX_IMAGES=10`
- `EMBEDDING_PROVIDER=local`
- `EMBEDDING_MODEL=E:\\workspace\\botree-agent\\backend\\workspace\\Qwen\\Qwen3-Embedding-0.6B`
- `EMBEDDING_DEVICE=cuda`
- `EMBEDDING_BATCH_SIZE=8`
- `RERANKER_DEVICE=cuda`
- `RERANKER_BATCH_SIZE=8`
- `ACCESS_TOKEN_EXPIRE_MINUTES=720`

依据：`backend/.env`

### 日志目录和日志配置

| 项目 | 现状 | 依据 |
| --- | --- | --- |
| API / Worker 日志配置 | 代码中仅看到 `logging.basicConfig(...)`，默认输出到标准输出 / 标准错误；未看到 `FileHandler`、轮转日志或集中式日志配置 | `backend/main.py`、`backend/worker.py` |
| 数据库内业务日志 | 审计/业务日志写入数据库表：`operation_logs`、`review_logs`、`retrieval_traces` | `scripts/init_mysql.sql`、`backend/README.md` |
| 仓库内现存日志目录 | 存在 `backend/logs/` 目录，内含 `uvicorn-*.log`、`worker-*.log` 等文件 | `backend/logs/` |
| 仓库根下现存日志文件 | 存在 `backend/backend.log`、`backend/backend.err.log`、`backend/worker.runtime.log`、`backend/worker.runtime.err.log` | `backend/` 目录现状 |
| 现有日志文件来源 | `待确认`。仓库内未发现统一脚本把 API/Worker 日志写入上述文件的标准配置 | `backend/main.py`、`backend/worker.py`、`backend/start.sh`、`scripts/` |

---

## 3. 中间件依赖

| 服务 | 是否必需 | 当前配置 / 端口 | 用途 / 配置 | 依据 |
| --- | --- | --- | --- | --- |
| MySQL | 代码层 `非必需`（未配置时回退 SQLite）；当前部署配置 `已使用` | 当前 `.env`：`127.0.0.1:3306`，数据库名 `botree_agent`；版本要求 `待确认` | 存储用户、角色、项目、知识库、文档、审核、索引任务、图谱、检索 Trace 等核心结构化数据 | `backend/app/core/config.py`、`backend/app/core/database.py`、`backend/.env`、`scripts/init_mysql.sql` |
| Redis | API 启动 `非必需`；异步解析 / 构建 / 发布任务 `必需` | 当前 `.env`：`127.0.0.1:6379` | 提供 RQ 队列；`worker.py` 直接依赖 Redis；未配置时 `get_rq_queue()` 返回 `None`，解析任务会失败，构建/发布任务会报错 | `backend/app/core/redis.py`、`backend/app/services/index_task_service.py`、`backend/worker.py`、`backend/.env` |
| MinIO | 文档主流程 `非必需`；头像上传 `必需`；当前 `.env` `已配置` | 当前 `.env`：`127.0.0.1:9000`，bucket=`graphrag-documents` | 上传文档会同步写 MinIO；文档派生资产也会落 `document_assets`；用户头像接口要求 MinIO 可用 | `backend/app/core/minio.py`、`backend/app/knowledge/ingestion/upload_service.py`、`backend/app/services/user_service.py`、`backend/.env` |
| Milvus | 解析 / PageIndex / GraphRAG `非必需`；向量索引与向量检索 `必需` | 当前 `.env`：`127.0.0.1:19530`，collection=`botree_collection`，`EMBEDDING_DIM=1024` | 写入 Chunk 向量，支持语义检索；collection 缺失时会自动建表，字段必须包含 `id/knowledge_base_id/project_id/document_id/chunk_id/page_no/version_no/drawing_no/security_level/embedding` | `backend/app/core/milvus.py`、`backend/app/knowledge/indexing/milvus_indexer.py`、`backend/app/knowledge/indexing/index_service.py`、`backend/.env` |
| MinerU | 全局 `非必需`；启用后对非简单文本解析链路 `强依赖` | 当前 `.env`：`http://127.0.0.1:8000` | 非 `.txt/.md/.csv` 文档在启用 MinerU 时优先走 MinerU；调用方式为 `POST /tasks` -> `GET /tasks/{task_id}` -> `GET /tasks/{task_id}/result`；共享卷映射依赖 `MINERU_OUTPUT_HOST_DIR` / `MINERU_OUTPUT_CONTAINER_DIR` | `backend/app/knowledge/parsing/parser_service.py`、`backend/app/knowledge/parsing/mineru_parser.py`、`backend/app/knowledge/parsing/README.md`、`backend/.env` |

### 其他依赖服务 / 运行组件

| 组件 | 是否必需 | 说明 | 依据 |
| --- | --- | --- | --- |
| LibreOffice | Office 文档解析场景必需 | `doc/docx/ppt/pptx/xls/xlsx/odt/odp/ods/rtf` 先转 PDF 再解析；当前 `.env` 指向 Windows 安装路径 | `backend/app/services/libreoffice_conversion_service.py`、`backend/app/knowledge/parsing/parser_service.py`、`backend/.env` |
| `ripgrep` (`rg`) | 页级文本镜像检索必需 | `PageIndex` 文本镜像供 `ripgrep` 精确检索使用 | `backend/app/core/config.py`、`backend/app/services/page_index_service.py` |
| RQ Worker | 异步索引部署必需 | 异步 `mineru_parse` / `full_build` / `index_publish` 由 `python worker.py` 执行 | `backend/worker.py`、`backend/app/tasks/index_tasks.py`、`backend/app/services/index_task_service.py` |
| 外部 OpenAI-compatible API | LLM / 远程模型场景必需 | 当前 `.env` 指向 DashScope OpenAI-compatible 地址 | `backend/README.md`、`backend/app/services/llm_service.py`、`backend/.env` |

---

## 4. 模型服务配置

| 项目 | 结论 | 依据 |
| --- | --- | --- |
| 当前 LLM 配置方式 | `LLMService` 解析顺序为：显式传入配置 -> 数据库默认模型配置 `model_configs` -> 环境变量兜底；数据库初始化时会按环境变量自动 seed 默认模型 | `backend/app/services/llm_service.py`、`backend/app/repositories/model_repository.py`、`backend/app/core/database.py` |
| 当前使用的外部大模型 API | 当前 `.env` 指向 `https://dashscope.aliyuncs.com/compatible-mode/v1`，provider=`qwen_api`；代码层兼容任意 OpenAI-compatible 服务 | `backend/.env`、`backend/README.md`、`backend/app/services/llm_service.py` |
| 当前文本大模型 | 当前 `.env` 的主模型为 `qwen3.7-max`；若任务模型未单独覆盖，则默认值来自 `Settings`：`INTENT_LLM_MODEL=qwen3.5-flash`、`PLANNER_LLM_MODEL=qwen3.5-flash`、`EVIDENCE_JUDGE_FAST_MODEL=qwen3.5-flash`、`EVIDENCE_JUDGE_MODEL=qwen3.5-plus`、`ANSWER_LLM_MODEL=qwen3.5-plus`、`ANALYSIS_LLM_MODEL=qwen3.7-max` | `backend/.env`、`backend/app/core/config.py` |
| 当前视觉模型配置 | 视觉模型与普通 LLM 分开配置；当前 `.env`：provider=`qwen_api`、base=`DashScope compatible`、model=`qwen3.5-plus` | `backend/.env`、`backend/app/core/config.py`、`backend/app/services/llm_service.py` |
| Embedding 模型配置方式 | 优先取数据库默认 `model_type=embedding`；没有默认配置时回退到环境变量；数据库初始化时也会按环境变量 seed 默认 embedding 配置 | `backend/app/services/embedding_service.py`、`backend/app/repositories/model_repository.py`、`backend/app/core/database.py` |
| 当前 Embedding 模型 | 当前 `.env`：`EMBEDDING_PROVIDER=local`，本地模型路径 `E:\\workspace\\botree-agent\\backend\\workspace\\Qwen\\Qwen3-Embedding-0.6B`，`EMBEDDING_DEVICE=cuda`，`EMBEDDING_BATCH_SIZE=8` | `backend/.env`、`backend/app/services/embedding_service.py`、`backend/app/services/embedding_local.py` |
| Reranker 模型配置方式 | 只从数据库默认 `model_type=reranker` 读取；环境变量仅控制 device / batch / timeout，不提供 reranker 模型名或路径 | `backend/app/services/reranker_service.py`、`backend/app/repositories/model_repository.py`、`backend/app/core/config.py` |
| 当前 Reranker 模型 | `待确认`。仓库配置文件中未发现当前默认 reranker 模型名/路径，需要查询 `model_configs` 表 | `backend/app/services/reranker_service.py`、`backend/app/models/model_config.py`、`scripts/init_mysql.sql` |
| 是否使用 GPU | 配置层面：当前 `.env` 已设置 `EMBEDDING_DEVICE=cuda`、`RERANKER_DEVICE=cuda`；运行层面：本地 embedding / reranker 会先检查 CUDA，可在不可用时回退 CPU | `backend/.env`、`backend/app/services/embedding_local.py`、`backend/app/services/reranker_local.py` |
| 模型文件路径或配置项 | 本地 embedding 路径已写在 `.env`；Reranker 路径 / 远程地址依赖 `model_configs` 表；LLM / Vision 依赖 `LLM_BASE_URL`、`OPENAI_COMPATIBLE_BASE_URL`、`VISION_LLM_BASE_URL` 等配置项 | `backend/.env`、`backend/app/core/config.py`、`backend/app/core/database.py` |

### 与 `model_configs` 表的关系

- `model_configs` 表为运行期模型配置中心，表定义见 `scripts/init_mysql.sql` 与 `backend/app/models/model_config.py`
- `ModelConfigRepository.get_default(model_type)` 负责读取每类默认启用模型
- 启动初始化会根据环境变量补种默认 `llm`、任务型 `llm`、`embedding`；`reranker` 是否已种入当前仓库无法仅靠文件确认

依据：`backend/app/models/model_config.py`、`backend/app/repositories/model_repository.py`、`backend/app/core/database.py`、`scripts/init_mysql.sql`

---

## 5. 文件处理与索引流程

### 5.1 文件上传后的保存位置

| 项目 | 结论 | 依据 |
| --- | --- | --- |
| 本地上传目录 | 默认 `UPLOAD_DIR=storage/uploads`，解析后实际路径为 `backend/storage/uploads` | `backend/app/core/config.py` |
| PageIndex 文本镜像目录 | 默认 `PAGE_INDEX_DIR=storage/page_index`，实际路径为 `backend/storage/page_index` | `backend/app/core/config.py` |
| LibreOffice / 派生资产目录 | 默认 `LIBREOFFICE_WORK_DIR=storage/derived`，实际路径为 `backend/storage/derived` | `backend/app/core/config.py` |
| MinerU 共享卷宿主机目录 | 当前 `.env`：`\\\\wsl.localhost\\Ubuntu\\data\\mineru\\output` | `backend/.env`、`backend/app/core/config.py` |
| MinIO 同步 | 文档上传后若 MinIO 启用，会同步写入 `MINIO_BUCKET`；未启用时仅保存在本地 | `backend/app/knowledge/ingestion/upload_service.py`、`backend/app/core/minio.py` |

### 5.2 文档解析流程

1. 上传文档后，`DocumentService.upload_document()` 创建 `documents`、`document_versions` 记录，并立即创建 `index_tasks` 中的 `mineru_parse` 任务。  
   依据：`backend/app/services/document_service.py`、`backend/app/services/index_task_service.py`
2. `ParserService.parse_document()` 根据文件类型选择解析链路：
   - `.txt/.md/.csv` -> `SimpleTextParser`
   - `.pdf` -> MinerU（若启用）或本地简单解析
   - Office 文档 -> `LibreOfficeConversionService` 转 PDF -> MinerU / 本地解析  
   依据：`backend/app/knowledge/parsing/parser_service.py`、`backend/app/knowledge/parsing/README.md`
3. `DocumentService._parse_to_chunks()` 会：
   - 清洗解析结果
   - 写入 `document_pages`、`document_page_blocks`
   - 写入 `document_chunks`
   - 记录转换 PDF、MinerU 原始 JSON、页图、块图等派生资产到 `document_assets`  
   依据：`backend/app/services/document_service.py`、`backend/app/services/page_index_service.py`、`docs/database/database_design.md`
4. 真正执行异步解析的后台函数是 `run_parse_document_task()`。  
   依据：`backend/app/tasks/index_tasks.py`

### 5.3 审核流程

1. `ReviewService.submit_review()`：
   - 校验文档 / 版本状态
   - 将文档或版本状态推进到 `submitted` / `reviewing`
   - 新增或复用 `review_tasks`
   - 写入 `review_logs`  
   依据：`backend/app/services/review_service.py`
2. `ReviewService.approve()`：
   - 将 `review_tasks` 标记为 `approved`
   - 将 `document_versions` 标记为 `approved`
   - 当前版本对应的 `documents` 也会推进到 `approved` / `published` 类状态  
   依据：`backend/app/services/review_service.py`
3. `ReviewService.reject()`：
   - 将任务 / 版本 / 文档推进到 `rejected`
   - 文档状态回到待审核侧状态  
   依据：`backend/app/services/review_service.py`
4. 解析质量确认是另一条独立流程：`PageIndexService.quality_check()` 会把文档 `index_status` 置为 `parsed` 或 `failed`。  
   依据：`backend/app/services/page_index_service.py`

### 5.4 索引构建流程

1. 文档构建前置条件：
   - 文档必须审核通过
   - 文档必须已有 chunks
   - 文档不能处于 `parsed_pending_review` 等禁止状态  
   依据：`backend/app/services/document_service.py`
2. `IndexPipelineService.build_all()` 的主要步骤：
   - `PageIndexService.build_page_indexes()` 构建页级索引和文本镜像
   - 若 Milvus 启用，则 `IndexService.index_document()` 写入向量库
   - `GraphIndexService.build_document_graph()` 构建 MySQL 图谱
   - `publish=True` 时再统一发布 PageIndex / GraphRAG  
   依据：`backend/app/services/index_pipeline_service.py`
3. 异步任务类型至少包含：
   - `mineru_parse`
   - `full_build`
   - `index_publish`  
   依据：`backend/app/services/index_task_service.py`

### 5.5 版本更新时旧索引失效逻辑

| 场景 | 当前逻辑 | 依据 |
| --- | --- | --- |
| 切换当前版本 / 回滚 | 旧版本 chunks 会被置为 `obsolete`；已绑定的旧向量会做 best-effort 删除；文档 / 目标版本 `index_status` 重置为 `not_indexed`，要求重建 | `backend/app/services/document_service.py` |
| 更新文档密级 | 文档、版本、chunk、page、page_index 的密级会同步更新；已索引文档会被标记失效，`page_indexes` 的 `staging/published` 会变 `obsolete` | `backend/app/services/document_service.py` |
| 软删除 / 物理删除 | 会作废或清理 page index、Milvus 向量、MinIO 对象、本地派生文件和图谱等外部资源 | `backend/app/services/document_service.py` |
| 在线检索范围 | 仅允许当前版本、已审核、已索引、chunk 活跃的内容进入检索和问答 | `backend/app/services/project_document_policy_service.py`、`backend/app/services/evidence_access_guard_service.py`、`docs/database/database_design.md` |

### 5.6 涉及的数据库表

| 表 | 用途 | 依据 |
| --- | --- | --- |
| `documents` | 文档主表，保存当前版本状态、审核状态、索引状态、密级等 | `scripts/init_mysql.sql`、`docs/database/database_design.md` |
| `document_versions` | 文档版本表 | `scripts/init_mysql.sql`、`docs/database/database_design.md` |
| `document_chunks` | Chunk 结果表 | `scripts/init_mysql.sql`、`docs/database/database_design.md` |
| `document_pages` | 页级解析结果表 | `scripts/init_mysql.sql`、`docs/database/database_design.md` |
| `document_page_blocks` | 页内块级结构表 | `scripts/init_mysql.sql`、`docs/database/database_design.md` |
| `document_assets` | 转换 PDF、MinerU 原始结果、页图、块图等资产表 | `scripts/init_mysql.sql`、`docs/database/database_design.md` |
| `page_indexes` | 页级检索索引表，关联本地文本镜像 | `scripts/init_mysql.sql`、`docs/database/database_design.md` |
| `index_tasks` | 解析 / 构建 / 发布后台任务表 | `scripts/init_mysql.sql`、`backend/app/services/index_task_service.py` |
| `review_tasks` | 审核任务表 | `scripts/init_mysql.sql`、`backend/app/services/review_service.py` |
| `review_logs` | 审核日志表 | `scripts/init_mysql.sql`、`backend/app/services/review_service.py` |
| `graph_entities` / `graph_relations` | GraphRAG 第一阶段图谱表 | `scripts/init_mysql.sql`、`docs/database/database_design.md` |
| `retrieval_traces` | 问答检索 Trace 表 | `scripts/init_mysql.sql` |
| `chat_citations` | 问答引用表 | `scripts/init_mysql.sql` |

---

## 6. 权限与安全

| 项目 | 结论 | 依据 |
| --- | --- | --- |
| 登录认证方式 | Bearer JWT；密码哈希算法为 `pbkdf2_sha256`（PBKDF2-HMAC-SHA256，120000 轮） | `backend/app/core/security.py`、`backend/app/api/deps.py`、`backend/app/services/auth_service.py` |
| 用户、角色、菜单、按钮权限相关表 | 数据表：`users`、`roles`、`permissions`、`user_roles`、`role_permissions`、`departments`；未发现独立“菜单表 / 按钮表”，菜单与动作权限注册主要在代码 `rbac.py`，数据库保存的是权限码 | `scripts/init_mysql.sql`、`backend/app/core/rbac.py` |
| 项目权限控制方式 | 结合 JWT 当前用户、权限码校验、角色数据范围、项目密级、项目成员关系、管理员绕过逻辑综合判断 | `backend/app/api/deps.py`、`backend/app/services/project_access_service.py` |
| 文档密级控制方式 | 统一使用 `public / internal / confidential`；文档、版本、chunk、page、page_index、Milvus metadata 都带密级 | `backend/app/core/security_levels.py`、`backend/app/services/document_service.py`、`backend/app/knowledge/indexing/milvus_indexer.py` |
| 问答检索时权限过滤逻辑 | 先做检索器侧过滤（如 Milvus expr / PageIndex / ripgrep 范围），再由 `EvidenceAccessGuardService` 回查 MySQL，重新校验项目归属、文档状态、当前版本、chunk 状态、密级与权限 | `backend/app/services/project_document_policy_service.py`、`backend/app/services/evidence_access_guard_service.py`、`backend/app/retrieval/README.md` |

### 权限相关补充

- `require_permission()` / `require_any_permission()` 是后端接口级权限守卫。  
  依据：`backend/app/api/deps.py`
- 当前运行代码会删除 `knowledge_base_permissions` 表；但设计文档仍保留该表描述。  
  依据：`backend/app/core/database.py`、`docs/database/database_design.md`

---

## 7. 端口与服务清单

| 服务 / 组件 | 当前端口 / 地址 | 结论 | 依据 |
| --- | --- | --- | --- |
| 前端开发服务 | `5173` | 已明确 | `frontend/vite.config.ts`、`frontend/README.md` |
| 前端生产服务 | `待确认` | 仓库只提供静态构建，不包含 Nginx / CDN / 生产端口定义 | `frontend/README.md` |
| 后端 API | `8888` | 已明确 | `backend/start.sh`、`backend/README.md`、`backend/app/core/config.py` |
| Swagger | `8888/docs` | 已明确 | `backend/README.md` |
| MySQL | `3306` | 当前 `.env` 已配置 | `backend/.env`、`backend/app/core/config.py` |
| Redis | `6379` | 当前 `.env` 已配置 | `backend/.env`、`backend/app/core/config.py` |
| MinIO API | `9000` | 当前 `.env` 已配置 | `backend/.env` |
| MinIO Console | `待确认` | 仓库未发现 Console 端口配置 | 仓库内未发现对应配置文件 |
| Milvus | `19530` | 当前 `.env` 已配置 | `backend/.env`、`backend/app/core/config.py` |
| MinerU | `8000` | 当前 `.env` 已配置 | `backend/.env` |
| RQ Worker | 无独立端口 | 进程型后台组件，通过 Redis 队列工作 | `backend/worker.py` |
| LibreOffice | 无网络端口 | 本地进程方式调用 CLI | `backend/app/services/libreoffice_conversion_service.py` |
| `ripgrep` | 无网络端口 | 本地二进制命令 | `backend/app/core/config.py` |

### `BACKEND_URL` / `FRONTEND_URL` 现状

- 只在 `backend/.env` 中发现：
  - `BACKEND_URL=http://127.0.0.1:8888`
  - `FRONTEND_URL=http://127.0.0.1:5173`
- 当前仓库内未发现这些变量被 `Settings` 或主业务代码消费。

结论：这两个变量当前更像“环境备注项”而非后端正式运行配置。  
依据：`backend/.env`、`backend/app/core/config.py`、仓库全文检索结果

---

## 8. 部署风险

| 风险点 | 当前现状 | 依据 |
| --- | --- | --- |
| 真实敏感配置已出现在 `backend/.env` | 仓库工作区存在真实运行 `.env`，其中包含数据库口令、Redis 口令、MinIO 密钥、LLM API Key、JWT 密钥等敏感项 | `backend/.env` |
| Python 版本未固定 | 未发现 Python 版本声明文件；部署环境一致性无法仅靠仓库保证 | `backend/requirements.txt`、`backend/README.md` |
| 当前启动脚本仍是开发模式 | `backend/start.sh` 使用 `uvicorn ... --reload`，不适合生产常驻 | `backend/start.sh` |
| CORS 过宽 | `allow_origins=["*"]`、`allow_credentials=True`，生产暴露面偏大 | `backend/main.py` |
| 启动时自动建表 / 迁移 / seed | `init_database()` 仍使用 `Base.metadata.create_all()`，并在运行时执行自定义迁移与默认数据 seed；生产变更可控性较弱 | `backend/app/core/database.py` |
| 权限设计文档与运行代码不一致 | 设计文档仍描述 `knowledge_base_permissions`，但运行代码会在迁移时直接 `DROP TABLE knowledge_base_permissions` | `docs/database/database_design.md`、`backend/app/core/database.py` |
| 存在大量本地硬编码路径 / 地址 / 端口 | 例如前端代理 `127.0.0.1:8888`、本地 embedding 路径、MinerU WSL UNC 路径、LibreOffice Windows 安装路径、`.env` 中一系列 `127.0.0.1` 地址 | `frontend/vite.config.ts`、`backend/.env`、`backend/.env.example` |
| SQL 初始化脚本存在环境耦合项 | `scripts/init_mysql.sql` 中包含 DashScope API Base、Windows 本地 embedding 路径等种子值 | `scripts/init_mysql.sql` |
| `BACKEND_URL` / `FRONTEND_URL` 配置漂移风险 | 当前仅在 `.env` 中存在，代码未消费，容易让运维误以为它们会生效 | `backend/.env`、`backend/app/core/config.py` |
| Reranker 实际模型不在环境文件里 | 当前环境变量只声明 `RERANKER_DEVICE / BATCH / TIMEOUT`，默认 reranker 模型依赖数据库 `model_configs`；若库内缺配置会直接不可用 | `backend/app/services/reranker_service.py`、`backend/app/core/config.py` |
| Redis / Worker 缺失会影响主链路 | 未配置 Redis 时：解析任务会失败，构建/发布任务会直接报错；异步索引部署必须额外维护 Worker 进程 | `backend/app/core/redis.py`、`backend/app/services/index_task_service.py`、`backend/worker.py` |
| 日志落盘方式不统一 | 仓库虽有 `backend/logs/` 与若干 `.log` 文件，但代码内未发现统一的文件日志、轮转与清理配置 | `backend/main.py`、`backend/worker.py`、`backend/logs/`、`backend/` |
| 数据库误回退到 SQLite 的风险 | 若 MySQL / `DATABASE_URL` 未配置，系统会自动回退 `sqlite:///./botree_knowledge.db`，可能掩盖部署缺项 | `backend/app/core/config.py` |

### 当前不适合生产环境的启动方式

1. `backend/start.sh` 使用 `--reload`
2. API 与 Worker 没有看到 `systemd` / `supervisor` / `docker-compose` / `k8s` 形式的标准常驻管理脚本
3. 前端只有 `npm run build`，未发现静态资源发布脚本

依据：`backend/start.sh`、`backend/worker.py`、`frontend/README.md`、仓库文件清单

### 当前需要补充的运维脚本

以下脚本或部署编排文件当前仓库内未发现，建议补充：

1. API 生产启动脚本  
   包括固定工作目录、环境加载、进程守护、日志落盘 / 轮转
2. Worker 常驻脚本  
   单独管理 `python worker.py`
3. 前端静态发布脚本  
   包括构建、产物同步、缓存刷新
4. 数据库迁移 / 初始化脚本  
   建议将生产迁移与运行时 `create_all` 解耦
5. 中间件健康检查 / 等待脚本  
   MySQL、Redis、MinIO、Milvus、MinerU、外部 LLM API
6. 日志清理 / 轮转脚本
7. 敏感配置分发模板  
   区分开发、测试、生产环境

依据：`backend/start.sh`、`backend/worker.py`、`scripts/init_mysql.sql`、仓库文件清单

---

## 附：当前部署画像（仅基于现有 `.env`）

- 前端开发态：`127.0.0.1:5173`
- 后端 API：`127.0.0.1:8888`
- MySQL：`127.0.0.1:3306 / botree_agent`
- Redis：`127.0.0.1:6379`
- MinIO：`127.0.0.1:9000 / graphrag-documents`
- Milvus：`127.0.0.1:19530 / botree_collection`
- MinerU：`127.0.0.1:8000`
- LLM / Vision：DashScope OpenAI-compatible
- Embedding：本地 Qwen embedding，目标设备 `cuda`
- Reranker：设备设为 `cuda`，具体模型 `待确认`

依据：`backend/.env`

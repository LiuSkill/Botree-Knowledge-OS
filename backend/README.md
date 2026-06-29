# Botree Backend

## 功能

FastAPI 后端负责认证、用户角色、项目、知识库、文档上传、审核发布、解析分块、索引、检索、AI 项目问答、AI 基础问答、引用来源、操作日志、问答审计和模型配置。

## 调用关系

Controller 位于 `app/api`，只负责请求参数、依赖注入和响应转换；业务逻辑进入 `app/services`；数据访问进入 `app/repositories`；数据库模型在 `app/models`；请求和响应模型在 `app/schemas`。

## 输入

- `backend/.env`：真实运行配置，包括 MySQL、Redis、MinIO、Milvus、MinerU、LLM 和 JWT。
- 上传文件：通过 `/api/knowledge-bases/{id}/documents/upload` 进入本地真实存储；配置 MinIO 后会同步写入对象存储。
- API 请求：全部通过 Pydantic Schema 校验，问答请求通过 `chat_type` 区分 `project_chat` 和 `base_chat`。

## 真实运行配置

- LLM 回答必须配置真实 OpenAI-compatible 服务：`LLM_BASE_URL` 或 `OPENAI_COMPATIBLE_BASE_URL`、`LLM_MODEL`，以及需要鉴权时的 `LLM_API_KEY` 或 `OPENAI_API_KEY`。
- PID/P&ID 图片问答必须配置独立视觉模型：`VISION_LLM_BASE_URL`、`VISION_LLM_MODEL=qwen3.5-plus`，以及需要鉴权时的 `VISION_LLM_API_KEY`；也可以在模型配置中新增 `model_type=vision_llm` 的默认模型覆盖环境变量。
- 解析默认读取真实本地文件；配置 `MINERU_BASE_URL` 后优先调用 MinerU 真实解析服务。
- 构建索引必须配置真实 Embedding 与 Milvus：本地模型使用 `EMBEDDING_PROVIDER=local` 和 `EMBEDDING_MODEL=E:\workspace\botree-agent\backend\workspace\Qwen\Qwen3-Embedding-0.6B`；远程模型必须提供 Embedding API Base/Key、`MILVUS_HOST`、`MILVUS_PORT`、`EMBEDDING_DIM`。
- 系统已禁用 `fallback/mock/demo` 等模型供应商；缺少真实配置时接口会返回明确错误，不再生成假回答或假索引成功。

## 输出

- FastAPI 服务固定端口：`8888`
- Swagger 文档：`/docs`
- 统一响应：`{ code, message, data }`
- 操作日志和问答审计：写入数据库。

## 示例

```bash
python -m pip install -r requirements.txt
python -m uvicorn main:app --host 0.0.0.0 --port 8888
```
## Metrics

| Metric | Value |
| --- | ---: |
| MAP@10 | 0.62994 |
| MAP@100 | 0.63210 |
| MAP@5 | 0.62364 |
| MAP@50 | 0.63210 |
| MRR@10 | 0.64137 |
| MRR@100 | 0.64298 |
| MRR@5 | 0.63633 |
| MRR@50 | 0.64298 |
| NDCG@10 | 0.65712 |
| NDCG@100 | 0.66467 |
| NDCG@5 | 0.64407 |
| NDCG@50 | 0.66467 |
| P@10 | 0.08133 |
| P@100 | 0.00850 |
| P@5 | 0.15267 |
| P@50 | 0.01700 |
| Recall@10 | 0.72672 |
| Recall@100 | 0.75639 |
| Recall@3 | 0.66117 |
| Recall@5 | 0.68978 |
| Recall@50 | 0.75639 |
## 自检

- 禁止 Controller 直接操作数据库。
- 禁止 `print()`，统一使用 `logging`。
- 禁止裸 SQL 拼接，使用 SQLAlchemy ORM。
- 项目问答必须绑定 `project_id`，基础问答默认不开放给外部用户。
- 未审核、未索引、无权限资料不得进入检索和问答引用。

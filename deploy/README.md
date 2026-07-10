# Botree Knowledge OS 内部试用环境部署说明

## 1. 交付目标

本交付物用于在一台全新 Ubuntu 服务器上部署当前项目的内部试用环境，满足以下约束：

- 前端使用 Nginx 静态资源部署。
- 后端 API 使用独立 Docker 容器部署。
- Worker 使用独立 Docker 容器部署。
- MySQL、Redis、MinIO、Milvus、MinerU 作为独立服务运行。
- `uploads`、`derived`、`page_index`、`mineru_output`、`models`、`logs` 全部使用宿主机持久化目录。
- API 容器与 Worker 容器挂载同一份 `/data/botree/page_index -> /app/storage/page_index`。
- 部署链路中禁止 `--reload`。
- 部署环境禁止 SQLite 回退，`ALLOW_SQLITE_FALLBACK=false`。
- CORS 不能继续使用 `*`。
- 不向仓库写入任何真实密钥。

## 2. 目录说明

```text
deploy/
├── .env.trial.example
├── README.md
├── docker/
│   ├── backend.Dockerfile
│   └── worker.Dockerfile
├── env/
│   └── backend.env.example
├── nginx/
│   └── botree-agent.conf
└── scripts/
    ├── 00_create_dirs.sh
    ├── 01_start_middlewares.sh
    ├── 02_build_backend.sh
    ├── 03_start_api.sh
    ├── 04_start_worker.sh
    ├── 05_build_frontend.sh
    ├── 06_publish_frontend.sh
    ├── 07_health_check.sh
    ├── 08_backup_mysql.sh
    ├── 09_backup_files.sh
    └── common.sh
```

## 3. 服务器前置条件

建议环境：

- Ubuntu 22.04 LTS 或 24.04 LTS
- 已安装 Docker Engine
- 已安装 Nginx
- 已安装 `curl`
- 能访问外部镜像仓库与 Python/NPM 依赖源

可选：

- 宿主机安装 Node.js 20，用于直接构建前端；若未安装，`05_build_frontend.sh` 会使用 `node:20-bookworm-slim` 容器构建。
- 若 MinerU 使用 GPU，请确保 NVIDIA 驱动与 Docker GPU Runtime 已准备完成。

## 4. 复制环境文件

```bash
cd /path/to/botree-knowledge
cp deploy/.env.trial.example deploy/.env.trial
cp deploy/env/backend.env.example deploy/env/backend.env
```

必须修改的值：

- `deploy/.env.trial`
  - `MYSQL_ROOT_PASSWORD`
  - `MINERU_IMAGE`（若你本地构建的标签不是 `mineru:latest`）
  - `MINERU_USE_GPU`
- `deploy/env/backend.env`
  - `CORS_ALLOW_ORIGINS`
  - `MYSQL_PASSWORD`
  - `REDIS_PASSWORD`
  - `MINIO_ACCESS_KEY`
  - `MINIO_SECRET_KEY`
  - `OPENAI_API_KEY`
  - `LLM_API_KEY`
  - `VISION_LLM_API_KEY`
  - `JWT_SECRET_KEY`
  - `DEFAULT_ADMIN_PASSWORD`
  - `EMBEDDING_MODEL`
  - `RERANKER_MODEL`

说明：

- `CORS_ALLOW_ORIGINS` 必须填写内部试用环境真实访问域名或地址，多个值用英文逗号分隔，禁止写成 `*`。
- `ALLOW_SQLITE_FALLBACK=false` 已在示例中固定，部署环境不要改回 `true`。
- `MINERU_OUTPUT_HOST_DIR` 在后端配置里虽然叫 `HOST_DIR`，但在容器部署场景下应填写容器内挂载路径 `/app/storage/mineru_output`。

## 5. 模型目录准备

宿主机模型目录统一放在：

```text
/data/botree/models
```

示例：

```text
/data/botree/models/Qwen/Qwen3-Embedding-0.6B
/data/botree/models/bge-reranker-v2-m3
/data/botree/models/mineru_cache
```

对应容器内映射：

- `/data/botree/models -> /app/models`

请保证：

- `EMBEDDING_MODEL` 指向 `/app/models/...`
- `RERANKER_MODEL` 指向 `/app/models/...`

脚本会在启动 API/Worker 前校验这两个模型目录是否存在。

## 6. 必须满足的挂载映射

当前交付物固定采用以下映射：

```text
/data/botree/uploads      -> /app/storage/uploads
/data/botree/derived      -> /app/storage/derived
/data/botree/page_index   -> /app/storage/page_index
/data/botree/mineru_output -> /app/storage/mineru_output
/data/botree/models       -> /app/models
/data/botree/logs         -> /app/logs
```

其中 API 与 Worker 都挂载同一份：

```text
/data/botree/page_index -> /app/storage/page_index
```

## 7. 一键创建目录

```bash
bash deploy/scripts/00_create_dirs.sh
```

该脚本会创建：

- 中间件数据目录
- 前后端运行目录
- `uploads / derived / page_index / mineru_output / models / logs`
- 备份目录

## 8. 启动中间件

```bash
bash deploy/scripts/01_start_middlewares.sh
```

会依次启动：

- MySQL
- Redis
- MinIO
- Milvus
- MinerU

补充说明：

- MinIO 会自动创建 `MINIO_BUCKET`。
- Milvus 采用单机模式，使用内嵌 etcd 与本地存储卷。
- `MINERU_IMAGE` 需要你提前准备好。本仓库脚本只负责启动，不在仓库中内置 MinerU 镜像构建逻辑。

MinerU 官方 Docker 参考：

- [MinerU Docker Deployment](https://opendatalab.github.io/MinerU/quick_start/docker_deployment/)

Milvus 单机 Docker 参考：

- [Milvus Standalone Docker Deployment](https://milvus.io/docs/scale-standalone.md)

## 9. 构建后端镜像

```bash
bash deploy/scripts/02_build_backend.sh
```

该脚本会：

1. 构建 API 镜像
2. 构建 Worker 镜像
3. 在 API 镜像中执行一次运行时校验：
   - `requirements.txt` 可安装成功
   - Python 关键依赖可导入
   - `soffice` 可执行
   - `rg` 可执行

## 10. 启动 API 与 Worker

```bash
bash deploy/scripts/03_start_api.sh
bash deploy/scripts/04_start_worker.sh
```

说明：

- API 容器启动前会执行 `alembic upgrade head`。
- API 与 Worker 均不会使用 `--reload`。
- API/Worker 都会把日志写入宿主机 `/data/botree/logs/`。
- 默认 reranker 配置会在应用启动时自动补到 `model_configs` 表：前提是 `RERANKER_PROVIDER` 与 `RERANKER_MODEL` 已正确配置，且数据库中还没有默认 reranker。

## 11. 构建并发布前端

```bash
bash deploy/scripts/05_build_frontend.sh
bash deploy/scripts/06_publish_frontend.sh
```

默认发布目录：

```text
/data/botree/frontend/current
```

前端构建默认使用：

```text
VITE_API_BASE_URL=/api
```

因此浏览器会通过 Nginx 同域代理访问后端，不改变现有前后端交互逻辑。

## 12. 安装 Nginx 配置

```bash
sudo cp deploy/nginx/botree-agent.conf /etc/nginx/sites-available/botree-agent.conf
sudo ln -sf /etc/nginx/sites-available/botree-agent.conf /etc/nginx/sites-enabled/botree-agent.conf
sudo nginx -t
sudo systemctl reload nginx
```

当前 Nginx 配置默认值：

- `root /data/botree/frontend/current`
- `proxy_pass http://127.0.0.1:18888`

若你调整了 `deploy/.env.trial` 中的前端目录或 API 端口，请同步修改 `deploy/nginx/botree-agent.conf`。

## 13. 健康检查

```bash
bash deploy/scripts/07_health_check.sh
```

健康检查会验证：

- 所有容器是否运行
- MySQL / Redis / MinIO / Milvus / MinerU / API 是否可访问
- Nginx 静态站点是否可访问
- API 镜像内是否包含 LibreOffice 与 ripgrep
- API 是否仍然回退 SQLite
- CORS 是否仍包含 `*`
- 默认 reranker 是否已经初始化到 `model_configs`
- API 与 Worker 是否共享同一份 PageIndex 宿主机目录

## 14. 备份

### 14.1 MySQL 备份

```bash
bash deploy/scripts/08_backup_mysql.sh
```

输出目录：

```text
/data/botree/backups/mysql
```

### 14.2 文件备份

```bash
bash deploy/scripts/09_backup_files.sh
```

输出目录：

```text
/data/botree/backups/files
```

默认打包目录：

- `uploads`
- `derived`
- `page_index`
- `mineru_output`
- `models`
- `logs`
- `frontend/current`

## 15. 推荐的首次部署顺序

```bash
bash deploy/scripts/00_create_dirs.sh
bash deploy/scripts/01_start_middlewares.sh
bash deploy/scripts/02_build_backend.sh
bash deploy/scripts/03_start_api.sh
bash deploy/scripts/04_start_worker.sh
bash deploy/scripts/05_build_frontend.sh
bash deploy/scripts/06_publish_frontend.sh
sudo cp deploy/nginx/botree-agent.conf /etc/nginx/sites-available/botree-agent.conf
sudo ln -sf /etc/nginx/sites-available/botree-agent.conf /etc/nginx/sites-enabled/botree-agent.conf
sudo nginx -t
sudo systemctl reload nginx
bash deploy/scripts/07_health_check.sh
```

## 16. 已处理的重点风险

本次补齐已覆盖以下部署风险：

- `CORS` 不再允许 `*`
- 部署环境通过 `ALLOW_SQLITE_FALLBACK=false` 禁止回退 SQLite
- API 与 Worker 使用同一份 PageIndex 宿主机目录
- 后端镜像内明确安装 `LibreOffice` 与 `ripgrep`
- `requirements.txt` 在镜像构建阶段被真实安装，并在脚本中做了运行时导入校验
- 默认 reranker 可通过配置自动补齐到 `model_configs`
- 所有脚本和示例配置都移除了 Windows 本地路径

## 17. 注意事项

- MinerU 镜像本身依赖较重，首次构建和首次拉起时间会明显长于其他服务。
- 若 Milvus 已存在旧数据目录，升级镜像版本前请先做快照或备份。
- 若使用真实域名访问，请同步更新 `CORS_ALLOW_ORIGINS` 与 Nginx `server_name`。
- 若需要 HTTPS，请在 Nginx 层额外补充证书与 443 server 块；当前交付物默认覆盖本地试用环境 HTTP。

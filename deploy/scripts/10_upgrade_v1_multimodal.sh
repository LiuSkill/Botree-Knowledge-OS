#!/usr/bin/env bash

set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=deploy/scripts/common.sh
source "${SCRIPT_DIR}/common.sh"

require_commands docker curl gzip tar realpath
load_env_files
validate_trial_env
validate_local_model_mounts

require_container_running "${MYSQL_CONTAINER_NAME}"
require_container_running "${REDIS_CONTAINER_NAME}"
require_container_running "${MINIO_CONTAINER_NAME}"
require_container_running "${MILVUS_CONTAINER_NAME}"

log "开始备份 1.0 数据；本脚本不会删除或重建 Milvus 集合"
bash "${SCRIPT_DIR}/08_backup_mysql.sh"
bash "${SCRIPT_DIR}/09_backup_files.sh"

for container_name in "${WORKER_CONTAINER_NAME}" "${API_CONTAINER_NAME}"; do
    if container_running "${container_name}"; then
        log "停止业务容器: ${container_name}"
        docker stop "${container_name}" >/dev/null
    fi
done

log "执行数据库迁移到当前 Alembic head"
docker run --rm \
    --network "${DOCKER_NETWORK}" \
    --env-file "${BACKEND_ENV_FILE}" \
    "${API_IMAGE}" \
    sh -lc 'set -eu; cd /app; python -m app.scripts.prepare_v1_multimodal_upgrade; alembic upgrade head; alembic current --check-heads'

log "启动并校验 1024 维视觉模型服务"
bash "${SCRIPT_DIR}/02_start_model_service.sh"

log "启动升级后的 API 与 Worker"
bash "${SCRIPT_DIR}/03_start_api.sh"
bash "${SCRIPT_DIR}/04_start_worker.sh"

log "1.0 服务升级完成；旧 Milvus 集合保持不变，尚未触发全量索引重建"

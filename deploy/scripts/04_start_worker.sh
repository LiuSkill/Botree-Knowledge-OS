#!/usr/bin/env bash

set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=deploy/scripts/common.sh
source "${SCRIPT_DIR}/common.sh"

require_commands docker
load_env_files
validate_trial_env
validate_local_model_mounts
ensure_docker_network

require_container_running "${MYSQL_CONTAINER_NAME}"
require_container_running "${REDIS_CONTAINER_NAME}"
require_container_running "${MINIO_CONTAINER_NAME}"
require_container_running "${MILVUS_CONTAINER_NAME}"
require_container_running "${MINERU_CONTAINER_NAME}"

docker_rm_if_exists "${WORKER_CONTAINER_NAME}"
docker run -d \
    --name "${WORKER_CONTAINER_NAME}" \
    --network "${DOCKER_NETWORK}" \
    --restart unless-stopped \
    --env-file "${BACKEND_ENV_FILE}" \
    -v "${UPLOADS_HOST_DIR}:/app/storage/uploads" \
    -v "${DERIVED_HOST_DIR}:/app/storage/derived" \
    -v "${PAGE_INDEX_HOST_DIR}:/app/storage/page_index" \
    -v "${MINERU_OUTPUT_DATA_DIR}:/app/storage/mineru_output" \
    -v "${MODELS_HOST_DIR}:/app/models" \
    -v "${LOGS_HOST_DIR}:/app/logs" \
    "${WORKER_IMAGE}" \
    sh -lc 'set -eu; cd /app; mkdir -p /app/logs; python worker.py 2>&1 | tee -a /app/logs/worker.log' >/dev/null

sleep 5
require_container_running "${WORKER_CONTAINER_NAME}"
log "Worker 启动完成"

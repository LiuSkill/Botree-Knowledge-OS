#!/usr/bin/env bash

set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=deploy/scripts/common.sh
source "${SCRIPT_DIR}/common.sh"

require_commands docker curl
load_env_files
validate_trial_env
validate_local_model_mounts
ensure_docker_network

require_container_running "${MYSQL_CONTAINER_NAME}"
require_container_running "${REDIS_CONTAINER_NAME}"
require_container_running "${MINIO_CONTAINER_NAME}"
require_container_running "${MILVUS_CONTAINER_NAME}"
require_container_running "${MINERU_CONTAINER_NAME}"

docker_rm_if_exists "${API_CONTAINER_NAME}"
docker run -d \
    --name "${API_CONTAINER_NAME}" \
    --network "${DOCKER_NETWORK}" \
    --restart unless-stopped \
    -p "${API_PORT}:${BACKEND_CONTAINER_PORT}" \
    --env-file "${BACKEND_ENV_FILE}" \
    -v "${UPLOADS_HOST_DIR}:/app/storage/uploads" \
    -v "${DERIVED_HOST_DIR}:/app/storage/derived" \
    -v "${PAGE_INDEX_HOST_DIR}:/app/storage/page_index" \
    -v "${MINERU_OUTPUT_DATA_DIR}:/app/storage/mineru_output" \
    -v "${MODELS_HOST_DIR}:/app/models" \
    -v "${LOGS_HOST_DIR}:/app/logs" \
    "${API_IMAGE}" \
    sh -lc 'set -eu; cd /app; alembic upgrade head; mkdir -p /app/logs; uvicorn main:app --host 0.0.0.0 --port 8888 2>&1 | tee -a /app/logs/api.log' >/dev/null

wait_for_http "http://127.0.0.1:${API_PORT}/api/health" "API" 90
log "API 启动完成"

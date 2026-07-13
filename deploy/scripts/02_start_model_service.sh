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

if ! model_service_enabled; then
    log "MODEL_SERVICE_ENABLED=false，跳过模型服务启动"
    exit 0
fi

docker image inspect "${MODEL_SERVICE_IMAGE}" >/dev/null 2>&1 || die "未找到模型服务镜像 ${MODEL_SERVICE_IMAGE}，请先构建后端镜像"

gpu_args=()
if [[ "$(to_lower "${MODEL_SERVICE_USE_GPU:-true}")" == "true" ]]; then
    gpu_args+=(--gpus all)
fi

docker_rm_if_exists "${MODEL_SERVICE_CONTAINER_NAME}"
docker run -d \
    --name "${MODEL_SERVICE_CONTAINER_NAME}" \
    --network "${DOCKER_NETWORK}" \
    --restart unless-stopped \
    "${gpu_args[@]}" \
    -p "${MODEL_SERVICE_PORT}:8890" \
    --env-file "${BACKEND_ENV_FILE}" \
    -v "${MODELS_HOST_DIR}:/app/models" \
    -v "${LOGS_HOST_DIR}:/app/logs" \
    "${MODEL_SERVICE_IMAGE}" \
    sh -lc 'set -eu; cd /app; mkdir -p /app/logs; uvicorn app.model_service.main:app --host 0.0.0.0 --port 8890 2>&1 | tee -a /app/logs/model-service.log' >/dev/null

wait_for_http "http://127.0.0.1:${MODEL_SERVICE_PORT}/health" "Model Service" 180
log "模型服务启动完成"

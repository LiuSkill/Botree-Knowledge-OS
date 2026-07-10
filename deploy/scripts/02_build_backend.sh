#!/usr/bin/env bash

set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=deploy/scripts/common.sh
source "${SCRIPT_DIR}/common.sh"

require_commands docker
load_env_files
validate_trial_env

log "构建 API 镜像 ${API_IMAGE}"
docker build --pull -f "${PROJECT_ROOT}/deploy/docker/backend.Dockerfile" -t "${API_IMAGE}" "${PROJECT_ROOT}"

log "构建 Worker 镜像 ${WORKER_IMAGE}"
docker build --pull -f "${PROJECT_ROOT}/deploy/docker/worker.Dockerfile" -t "${WORKER_IMAGE}" "${PROJECT_ROOT}"

log "校验 requirements.txt 安装结果与运行时依赖"
docker run --rm "${API_IMAGE}" sh -lc \
    'python -c "import fastapi, sqlalchemy, pymilvus, minio, redis, rq, torch, sentence_transformers" && soffice --headless --version >/dev/null && rg --version >/dev/null'

log "后端镜像构建与依赖校验完成"

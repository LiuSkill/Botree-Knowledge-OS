#!/usr/bin/env bash

set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=deploy/scripts/common.sh
source "${SCRIPT_DIR}/common.sh"

require_commands docker curl realpath
load_env_files
validate_trial_env
ensure_docker_network

docker_rm_if_exists "${MYSQL_CONTAINER_NAME}"
docker run -d \
    --name "${MYSQL_CONTAINER_NAME}" \
    --network "${DOCKER_NETWORK}" \
    --restart unless-stopped \
    -p "${MYSQL_PORT}:3306" \
    -e MYSQL_ROOT_PASSWORD="${MYSQL_ROOT_PASSWORD}" \
    -e MYSQL_DATABASE="${MYSQL_DATABASE}" \
    -e MYSQL_USER="${MYSQL_USER}" \
    -e MYSQL_PASSWORD="${MYSQL_PASSWORD}" \
    -v "${MYSQL_DATA_DIR}:/var/lib/mysql" \
    "${MYSQL_IMAGE}" \
    --character-set-server=utf8mb4 \
    --collation-server=utf8mb4_unicode_ci \
    --default-authentication-plugin=mysql_native_password >/dev/null
wait_for_mysql

docker_rm_if_exists "${REDIS_CONTAINER_NAME}"
docker run -d \
    --name "${REDIS_CONTAINER_NAME}" \
    --network "${DOCKER_NETWORK}" \
    --restart unless-stopped \
    -p "${REDIS_PORT}:6379" \
    -v "${REDIS_DATA_DIR}:/data" \
    "${REDIS_IMAGE}" \
    redis-server \
    --appendonly yes \
    --requirepass "${REDIS_PASSWORD}" >/dev/null
wait_for_redis

docker_rm_if_exists "${MINIO_CONTAINER_NAME}"
docker run -d \
    --name "${MINIO_CONTAINER_NAME}" \
    --network "${DOCKER_NETWORK}" \
    --restart unless-stopped \
    -p "${MINIO_API_PORT}:9000" \
    -p "${MINIO_CONSOLE_PORT}:9001" \
    -e MINIO_ROOT_USER="${MINIO_ACCESS_KEY}" \
    -e MINIO_ROOT_PASSWORD="${MINIO_SECRET_KEY}" \
    -v "${MINIO_DATA_DIR}:/data" \
    "${MINIO_IMAGE}" \
    server /data --console-address ":9001" >/dev/null
wait_for_http "http://127.0.0.1:${MINIO_API_PORT}/minio/health/live" "MinIO" 90
docker run --rm \
    --network "${DOCKER_NETWORK}" \
    --entrypoint /bin/sh \
    minio/mc:latest \
    -c "mc alias set local http://${MINIO_CONTAINER_NAME}:9000 ${MINIO_ACCESS_KEY} ${MINIO_SECRET_KEY} >/dev/null && mc mb --ignore-existing local/${MINIO_BUCKET} >/dev/null"

docker_rm_if_exists "${MILVUS_CONTAINER_NAME}"
docker run -d \
    --name "${MILVUS_CONTAINER_NAME}" \
    --network "${DOCKER_NETWORK}" \
    --restart unless-stopped \
    --security-opt seccomp:unconfined \
    -p "${MILVUS_PORT}:19530" \
    -p "${MILVUS_HTTP_PORT}:9091" \
    -e ETCD_USE_EMBED=true \
    -e ETCD_DATA_DIR=/var/lib/milvus/etcd \
    -e COMMON_STORAGETYPE=local \
    -v "${MILVUS_DATA_DIR}:/var/lib/milvus" \
    "${MILVUS_IMAGE}" \
    milvus run standalone >/dev/null
wait_for_http "http://127.0.0.1:${MILVUS_HTTP_PORT}/healthz" "Milvus" 120

docker image inspect "${MINERU_IMAGE}" >/dev/null 2>&1 || die "未找到 MinerU 镜像 ${MINERU_IMAGE}，请先按 deploy/README.md 中的官方文档完成构建"
docker_rm_if_exists "${MINERU_CONTAINER_NAME}"

gpu_args=()
if [[ "$(to_lower "${MINERU_USE_GPU:-false}")" == "true" ]]; then
    gpu_args+=(--gpus all)
fi

docker run -d \
    --name "${MINERU_CONTAINER_NAME}" \
    --network "${DOCKER_NETWORK}" \
    --restart unless-stopped \
    "${gpu_args[@]}" \
    -p "${MINERU_PORT}:8000" \
    -v "${MINERU_OUTPUT_DATA_DIR}:/workspace/output" \
    -v "${MINERU_MODEL_CACHE_DIR}:/root/.cache/modelscope" \
    "${MINERU_IMAGE}" \
    mineru-api --host 0.0.0.0 --port 8000 >/dev/null
wait_for_http "http://127.0.0.1:${MINERU_PORT}/docs" "MinerU" 180

log "中间件启动完成"

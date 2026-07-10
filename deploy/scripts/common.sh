#!/usr/bin/env bash

set -Eeuo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DEPLOY_ROOT="${PROJECT_ROOT}/deploy"
DEFAULT_TRIAL_ENV_FILE="${DEPLOY_ROOT}/.env.trial"
DEFAULT_BACKEND_ENV_FILE="${DEPLOY_ROOT}/env/backend.env"

log() {
    printf '[%s] %s\n' "$(date '+%F %T')" "$*"
}

die() {
    printf '[%s] ERROR: %s\n' "$(date '+%F %T')" "$*" >&2
    exit 1
}

require_commands() {
    local command_name
    for command_name in "$@"; do
        command -v "${command_name}" >/dev/null 2>&1 || die "缺少命令: ${command_name}"
    done
}

to_lower() {
    printf '%s' "$1" | tr '[:upper:]' '[:lower:]'
}

ensure_non_empty() {
    local var_name="$1"
    local value="${!var_name:-}"
    [[ -n "${value}" ]] || die "缺少环境变量: ${var_name}"
}

ensure_linux_path() {
    local value="$1"
    local label="$2"
    [[ -n "${value}" ]] || return 0
    if [[ "${value}" =~ ^[A-Za-z]:[\\/].* ]]; then
        die "${label} 不能使用 Windows 路径: ${value}"
    fi
}

load_env_files() {
    local trial_env_file="${TRIAL_ENV_FILE:-${DEFAULT_TRIAL_ENV_FILE}}"
    [[ -f "${trial_env_file}" ]] || die "未找到 ${trial_env_file}，请先由 deploy/.env.trial.example 复制生成"

    set -a
    # shellcheck disable=SC1090
    source "${trial_env_file}"

    local backend_env_file="${BACKEND_ENV_FILE:-${DEFAULT_BACKEND_ENV_FILE}}"
    if [[ "${backend_env_file}" != /* ]]; then
        backend_env_file="${PROJECT_ROOT}/${backend_env_file}"
    fi
    [[ -f "${backend_env_file}" ]] || die "未找到 ${backend_env_file}，请先由 deploy/env/backend.env.example 复制生成"
    # shellcheck disable=SC1090
    source "${backend_env_file}"
    set +a

    export TRIAL_ENV_FILE="${trial_env_file}"
    export BACKEND_ENV_FILE="${backend_env_file}"
}

assert_under_dir() {
    local target_dir="$1"
    local base_dir="$2"
    local resolved_target
    local resolved_base
    resolved_target="$(realpath -m "${target_dir}")"
    resolved_base="$(realpath -m "${base_dir}")"
    case "${resolved_target}" in
        "${resolved_base}" | "${resolved_base}"/*) ;;
        *)
            die "目录 ${resolved_target} 不在允许范围 ${resolved_base} 内"
            ;;
    esac
}

docker_rm_if_exists() {
    local container_name="$1"
    if docker ps -a --format '{{.Names}}' | grep -Fxq "${container_name}"; then
        log "删除旧容器 ${container_name}"
        docker rm -f "${container_name}" >/dev/null
    fi
}

ensure_docker_network() {
    if ! docker network inspect "${DOCKER_NETWORK}" >/dev/null 2>&1; then
        log "创建 Docker 网络 ${DOCKER_NETWORK}"
        docker network create "${DOCKER_NETWORK}" >/dev/null
    fi
}

container_running() {
    local container_name="$1"
    docker inspect -f '{{.State.Running}}' "${container_name}" 2>/dev/null | grep -Fxq 'true'
}

require_container_running() {
    local container_name="$1"
    container_running "${container_name}" || die "容器未运行: ${container_name}"
}

wait_for_http() {
    local url="$1"
    local label="$2"
    local max_attempts="${3:-60}"
    local attempt

    for attempt in $(seq 1 "${max_attempts}"); do
        if curl -fsS "${url}" >/dev/null 2>&1; then
            log "${label} 就绪: ${url}"
            return 0
        fi
        sleep 2
    done
    die "${label} 启动超时: ${url}"
}

wait_for_mysql() {
    local max_attempts="${1:-90}"
    local attempt

    for attempt in $(seq 1 "${max_attempts}"); do
        if docker exec "${MYSQL_CONTAINER_NAME}" mysqladmin ping -h 127.0.0.1 -uroot "-p${MYSQL_ROOT_PASSWORD}" --silent >/dev/null 2>&1; then
            log "MySQL 就绪"
            return 0
        fi
        sleep 2
    done
    die "MySQL 启动超时"
}

wait_for_redis() {
    local max_attempts="${1:-60}"
    local attempt

    for attempt in $(seq 1 "${max_attempts}"); do
        if docker exec "${REDIS_CONTAINER_NAME}" redis-cli -a "${REDIS_PASSWORD}" ping 2>/dev/null | grep -Fxq 'PONG'; then
            log "Redis 就绪"
            return 0
        fi
        sleep 2
    done
    die "Redis 启动超时"
}

mount_source_for() {
    local container_name="$1"
    local destination_path="$2"
    docker inspect -f "{{range .Mounts}}{{if eq .Destination \"${destination_path}\"}}{{.Source}}{{end}}{{end}}" "${container_name}"
}

validate_trial_env() {
    ensure_non_empty BOTREE_BASE_DIR
    ensure_non_empty DOCKER_NETWORK
    ensure_non_empty API_IMAGE
    ensure_non_empty WORKER_IMAGE
    ensure_non_empty API_CONTAINER_NAME
    ensure_non_empty WORKER_CONTAINER_NAME
    ensure_non_empty MYSQL_IMAGE
    ensure_non_empty MYSQL_CONTAINER_NAME
    ensure_non_empty MYSQL_ROOT_PASSWORD
    ensure_non_empty REDIS_IMAGE
    ensure_non_empty REDIS_CONTAINER_NAME
    ensure_non_empty MINIO_IMAGE
    ensure_non_empty MINIO_CONTAINER_NAME
    ensure_non_empty MILVUS_IMAGE
    ensure_non_empty MILVUS_CONTAINER_NAME
    ensure_non_empty MINERU_IMAGE
    ensure_non_empty MINERU_CONTAINER_NAME
    ensure_non_empty FRONTEND_PUBLISH_DIR
    ensure_non_empty LOGS_HOST_DIR
    ensure_non_empty MYSQL_DATA_DIR
    ensure_non_empty REDIS_DATA_DIR
    ensure_non_empty MINIO_DATA_DIR
    ensure_non_empty MILVUS_DATA_DIR
    ensure_non_empty UPLOADS_HOST_DIR
    ensure_non_empty DERIVED_HOST_DIR
    ensure_non_empty PAGE_INDEX_HOST_DIR
    ensure_non_empty MINERU_OUTPUT_DATA_DIR
    ensure_non_empty MINERU_MODEL_CACHE_DIR
    ensure_non_empty MODELS_HOST_DIR
    ensure_non_empty BACKUP_MYSQL_DIR
    ensure_non_empty BACKUP_FILES_DIR

    ensure_non_empty MYSQL_HOST
    ensure_non_empty MYSQL_DATABASE
    ensure_non_empty MYSQL_USER
    ensure_non_empty MYSQL_PASSWORD
    ensure_non_empty REDIS_HOST
    ensure_non_empty REDIS_PASSWORD
    ensure_non_empty MINIO_ENDPOINT
    ensure_non_empty MINIO_ACCESS_KEY
    ensure_non_empty MINIO_SECRET_KEY
    ensure_non_empty MINIO_BUCKET
    ensure_non_empty MILVUS_HOST
    ensure_non_empty MINERU_BASE_URL
    ensure_non_empty CORS_ALLOW_ORIGINS
    ensure_non_empty JWT_SECRET_KEY

    ensure_linux_path "${BOTREE_BASE_DIR}" "BOTREE_BASE_DIR"
    ensure_linux_path "${MYSQL_DATA_DIR}" "MYSQL_DATA_DIR"
    ensure_linux_path "${REDIS_DATA_DIR}" "REDIS_DATA_DIR"
    ensure_linux_path "${MINIO_DATA_DIR}" "MINIO_DATA_DIR"
    ensure_linux_path "${MILVUS_DATA_DIR}" "MILVUS_DATA_DIR"
    ensure_linux_path "${UPLOADS_HOST_DIR}" "UPLOADS_HOST_DIR"
    ensure_linux_path "${DERIVED_HOST_DIR}" "DERIVED_HOST_DIR"
    ensure_linux_path "${PAGE_INDEX_HOST_DIR}" "PAGE_INDEX_HOST_DIR"
    ensure_linux_path "${MINERU_OUTPUT_DATA_DIR}" "MINERU_OUTPUT_DATA_DIR"
    ensure_linux_path "${MODELS_HOST_DIR}" "MODELS_HOST_DIR"
    ensure_linux_path "${LOGS_HOST_DIR}" "LOGS_HOST_DIR"
    ensure_linux_path "${FRONTEND_PUBLISH_DIR}" "FRONTEND_PUBLISH_DIR"
    ensure_linux_path "${BACKUP_MYSQL_DIR}" "BACKUP_MYSQL_DIR"
    ensure_linux_path "${BACKUP_FILES_DIR}" "BACKUP_FILES_DIR"
    ensure_linux_path "${UPLOAD_DIR}" "UPLOAD_DIR"
    ensure_linux_path "${PAGE_INDEX_DIR}" "PAGE_INDEX_DIR"
    ensure_linux_path "${MINERU_OUTPUT_HOST_DIR}" "MINERU_OUTPUT_HOST_DIR"
    ensure_linux_path "${LIBREOFFICE_WORK_DIR}" "LIBREOFFICE_WORK_DIR"
    ensure_linux_path "${EMBEDDING_MODEL:-}" "EMBEDDING_MODEL"
    ensure_linux_path "${RERANKER_MODEL:-}" "RERANKER_MODEL"

    [[ "${UPLOAD_DIR}" == "/app/storage/uploads" ]] || die "UPLOAD_DIR 必须为 /app/storage/uploads"
    [[ "${PAGE_INDEX_DIR}" == "/app/storage/page_index" ]] || die "PAGE_INDEX_DIR 必须为 /app/storage/page_index"
    [[ "${MINERU_OUTPUT_HOST_DIR}" == "/app/storage/mineru_output" ]] || die "MINERU_OUTPUT_HOST_DIR 必须为 /app/storage/mineru_output"
    [[ "${LIBREOFFICE_WORK_DIR}" == "/app/storage/derived" ]] || die "LIBREOFFICE_WORK_DIR 必须为 /app/storage/derived"

    [[ "${DATABASE_URL:-}" != sqlite:* ]] || die "试用环境禁止使用 SQLite DATABASE_URL"
    [[ "$(to_lower "${ALLOW_SQLITE_FALLBACK:-true}")" == "false" ]] || die "试用环境必须设置 ALLOW_SQLITE_FALLBACK=false"
    [[ "${CORS_ALLOW_ORIGINS}" != *"*"* ]] || die "CORS_ALLOW_ORIGINS 不能包含 *"

    if [[ "${#JWT_SECRET_KEY}" -lt 32 ]]; then
        die "JWT_SECRET_KEY 至少需要 32 个字符"
    fi
}

resolve_host_model_path() {
    local container_model_path="$1"
    if [[ "${container_model_path}" == /app/models/* ]]; then
        printf '%s/%s\n' "${MODELS_HOST_DIR}" "${container_model_path#/app/models/}"
    fi
}

validate_local_model_mounts() {
    local embedding_provider_lower
    local reranker_provider_lower
    local model_path

    embedding_provider_lower="$(to_lower "${EMBEDDING_PROVIDER:-}")"
    reranker_provider_lower="$(to_lower "${RERANKER_PROVIDER:-}")"

    if [[ "${embedding_provider_lower}" == "local" ]]; then
        ensure_non_empty EMBEDDING_MODEL
        model_path="$(resolve_host_model_path "${EMBEDDING_MODEL}")"
        [[ -n "${model_path}" ]] || die "EMBEDDING_MODEL 建议使用 /app/models/* 形式，当前值: ${EMBEDDING_MODEL}"
        [[ -e "${model_path}" ]] || die "未找到 Embedding 模型目录: ${model_path}"
    fi

    case "${reranker_provider_lower}" in
        local|local_reranker|bge_local|qwen_local)
            ensure_non_empty RERANKER_MODEL
            model_path="$(resolve_host_model_path "${RERANKER_MODEL}")"
            [[ -n "${model_path}" ]] || die "RERANKER_MODEL 建议使用 /app/models/* 形式，当前值: ${RERANKER_MODEL}"
            [[ -e "${model_path}" ]] || die "未找到 Reranker 模型目录: ${model_path}"
            ;;
        "")
            die "缺少 RERANKER_PROVIDER，无法自动初始化默认 reranker 配置"
            ;;
    esac
}

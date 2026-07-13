#!/usr/bin/env bash

set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=deploy/scripts/common.sh
source "${SCRIPT_DIR}/common.sh"

require_commands docker curl
load_env_files
validate_trial_env

check_pass() {
    printf '[PASS] %s\n' "$1"
}

check_fail() {
    printf '[FAIL] %s\n' "$1" >&2
    return 1
}

failures=0

for container_name in \
    "${MYSQL_CONTAINER_NAME}" \
    "${REDIS_CONTAINER_NAME}" \
    "${MINIO_CONTAINER_NAME}" \
    "${MILVUS_CONTAINER_NAME}" \
    "${MINERU_CONTAINER_NAME}" \
    "${API_CONTAINER_NAME}" \
    "${WORKER_CONTAINER_NAME}"; do
    if container_running "${container_name}"; then
        check_pass "容器运行中: ${container_name}"
    else
        check_fail "容器未运行: ${container_name}" || failures=$((failures + 1))
    fi
done

if model_service_enabled; then
    if container_running "${MODEL_SERVICE_CONTAINER_NAME}"; then
        check_pass "容器运行中: ${MODEL_SERVICE_CONTAINER_NAME}"
    else
        check_fail "容器未运行: ${MODEL_SERVICE_CONTAINER_NAME}" || failures=$((failures + 1))
    fi
fi

if docker exec "${MYSQL_CONTAINER_NAME}" mysqladmin ping -h 127.0.0.1 -uroot "-p${MYSQL_ROOT_PASSWORD}" --silent >/dev/null 2>&1; then
    check_pass "MySQL 健康"
else
    check_fail "MySQL 健康检查失败" || failures=$((failures + 1))
fi

if docker exec "${REDIS_CONTAINER_NAME}" redis-cli -a "${REDIS_PASSWORD}" ping 2>/dev/null | grep -Fxq 'PONG'; then
    check_pass "Redis 健康"
else
    check_fail "Redis 健康检查失败" || failures=$((failures + 1))
fi

if curl -fsS "http://127.0.0.1:${MINIO_API_PORT}/minio/health/live" >/dev/null 2>&1; then
    check_pass "MinIO 健康"
else
    check_fail "MinIO 健康检查失败" || failures=$((failures + 1))
fi

if curl -fsS "http://127.0.0.1:${MILVUS_HTTP_PORT}/healthz" >/dev/null 2>&1; then
    check_pass "Milvus 健康"
else
    check_fail "Milvus 健康检查失败" || failures=$((failures + 1))
fi

if curl -fsS "http://127.0.0.1:${MINERU_PORT}/docs" >/dev/null 2>&1; then
    check_pass "MinerU 健康"
else
    check_fail "MinerU 健康检查失败" || failures=$((failures + 1))
fi

if model_service_enabled; then
    if curl -fsS "http://127.0.0.1:${MODEL_SERVICE_PORT}/health" | grep -q '"status":"ok"'; then
        check_pass "Model Service 健康"
    else
        check_fail "Model Service 健康检查失败" || failures=$((failures + 1))
    fi
fi

if curl -fsS "http://127.0.0.1:${API_PORT}/api/health" | grep -q '"status":"ok"'; then
    check_pass "API 健康"
else
    check_fail "API 健康检查失败" || failures=$((failures + 1))
fi

if curl -fsS "http://127.0.0.1/" >/dev/null 2>&1; then
    check_pass "Nginx 静态站点可访问"
else
    check_fail "Nginx 静态站点不可访问" || failures=$((failures + 1))
fi

if docker exec "${API_CONTAINER_NAME}" sh -lc 'command -v soffice >/dev/null && command -v rg >/dev/null'; then
    check_pass "API 镜像已包含 LibreOffice 与 ripgrep"
else
    check_fail "API 镜像缺少 LibreOffice 或 ripgrep" || failures=$((failures + 1))
fi

if docker exec "${API_CONTAINER_NAME}" python -c "from app.core.config import get_settings; assert not get_settings().effective_database_url.startswith('sqlite')" >/dev/null 2>&1; then
    check_pass "API 未回退 SQLite"
else
    check_fail "API 仍存在 SQLite 回退" || failures=$((failures + 1))
fi

if docker exec "${API_CONTAINER_NAME}" python -c "from app.core.config import get_settings; origins=get_settings().cors_allow_origins_list; assert origins and '*' not in origins" >/dev/null 2>&1; then
    check_pass "CORS 白名单已收敛"
else
    check_fail "CORS 仍然包含通配符或为空" || failures=$((failures + 1))
fi

if docker exec "${API_CONTAINER_NAME}" python -c "from app.core.database import SessionLocal; from app.repositories.model_repository import ModelConfigRepository; db=SessionLocal(); config=ModelConfigRepository(db).get_default('reranker'); db.close(); assert config is not None" >/dev/null 2>&1; then
    check_pass "默认 reranker 已初始化到 model_configs"
else
    check_fail "默认 reranker 未初始化到 model_configs" || failures=$((failures + 1))
fi

if container_running "${API_CONTAINER_NAME}" && container_running "${WORKER_CONTAINER_NAME}"; then
    api_page_index_mount="$(mount_source_for "${API_CONTAINER_NAME}" "/app/storage/page_index")"
    worker_page_index_mount="$(mount_source_for "${WORKER_CONTAINER_NAME}" "/app/storage/page_index")"
else
    api_page_index_mount=""
    worker_page_index_mount=""
fi

if [[ -n "${api_page_index_mount}" && "${api_page_index_mount}" == "${worker_page_index_mount}" ]]; then
    check_pass "API 与 Worker 共享同一份 PageIndex 目录"
else
    check_fail "API 与 Worker 未共享同一份 PageIndex 目录" || failures=$((failures + 1))
fi

if [[ "${failures}" -gt 0 ]]; then
    die "健康检查失败，共 ${failures} 项未通过"
fi

log "健康检查全部通过"

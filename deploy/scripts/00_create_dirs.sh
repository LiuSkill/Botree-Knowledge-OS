#!/usr/bin/env bash

set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=deploy/scripts/common.sh
source "${SCRIPT_DIR}/common.sh"

require_commands install realpath
load_env_files
validate_trial_env

for target_dir in \
    "${BOTREE_BASE_DIR}" \
    "${MYSQL_DATA_DIR}" \
    "${REDIS_DATA_DIR}" \
    "${MINIO_DATA_DIR}" \
    "${MILVUS_DATA_DIR}" \
    "${UPLOADS_HOST_DIR}" \
    "${DERIVED_HOST_DIR}" \
    "${PAGE_INDEX_HOST_DIR}" \
    "${MINERU_OUTPUT_DATA_DIR}" \
    "${MODELS_HOST_DIR}" \
    "${MINERU_MODEL_CACHE_DIR}" \
    "${LOGS_HOST_DIR}" \
    "${LOGS_HOST_DIR}/nginx" \
    "${FRONTEND_PUBLISH_DIR}" \
    "${BACKUP_MYSQL_DIR}" \
    "${BACKUP_FILES_DIR}"; do
    assert_under_dir "${target_dir}" "${BOTREE_BASE_DIR}"
    install -d -m 0755 "${target_dir}"
done

log "目录创建完成"

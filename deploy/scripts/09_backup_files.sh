#!/usr/bin/env bash

set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=deploy/scripts/common.sh
source "${SCRIPT_DIR}/common.sh"

require_commands tar install realpath
load_env_files
validate_trial_env

assert_under_dir "${BACKUP_FILES_DIR}" "${BOTREE_BASE_DIR}"
install -d -m 0755 "${BACKUP_FILES_DIR}"

for target_dir in \
    "${UPLOADS_HOST_DIR}" \
    "${DERIVED_HOST_DIR}" \
    "${PAGE_INDEX_HOST_DIR}" \
    "${MINERU_OUTPUT_DATA_DIR}" \
    "${MODELS_HOST_DIR}" \
    "${LOGS_HOST_DIR}" \
    "${FRONTEND_PUBLISH_DIR}"; do
    assert_under_dir "${target_dir}" "${BOTREE_BASE_DIR}"
done

timestamp="$(date '+%Y%m%d_%H%M%S')"
backup_file="${BACKUP_FILES_DIR}/botree_files_${timestamp}.tar.gz"

umask 077
tar -czf "${backup_file}" -C "${BOTREE_BASE_DIR}" \
    "$(basename "${UPLOADS_HOST_DIR}")" \
    "$(basename "${DERIVED_HOST_DIR}")" \
    "$(basename "${PAGE_INDEX_HOST_DIR}")" \
    "$(basename "${MINERU_OUTPUT_DATA_DIR}")" \
    "$(basename "${MODELS_HOST_DIR}")" \
    "$(basename "${LOGS_HOST_DIR}")" \
    "$(realpath --relative-to="${BOTREE_BASE_DIR}" "${FRONTEND_PUBLISH_DIR}")"

log "文件备份完成: ${backup_file}"

#!/usr/bin/env bash

set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=deploy/scripts/common.sh
source "${SCRIPT_DIR}/common.sh"

require_commands docker gzip install realpath
load_env_files
validate_trial_env
require_container_running "${MYSQL_CONTAINER_NAME}"

assert_under_dir "${BACKUP_MYSQL_DIR}" "${BOTREE_BASE_DIR}"
install -d -m 0755 "${BACKUP_MYSQL_DIR}"

timestamp="$(date '+%Y%m%d_%H%M%S')"
backup_file="${BACKUP_MYSQL_DIR}/botree_mysql_${timestamp}.sql.gz"

umask 077
docker exec "${MYSQL_CONTAINER_NAME}" sh -lc \
    'exec mysqldump --single-transaction --quick --routines --events -uroot -p"$MYSQL_ROOT_PASSWORD" "$MYSQL_DATABASE"' \
    | gzip -c > "${backup_file}"

log "MySQL 备份完成: ${backup_file}"

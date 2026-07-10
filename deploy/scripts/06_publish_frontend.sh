#!/usr/bin/env bash

set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=deploy/scripts/common.sh
source "${SCRIPT_DIR}/common.sh"

require_commands find cp install realpath
load_env_files

[[ -f "${PROJECT_ROOT}/frontend/dist/index.html" ]] || die "未找到 frontend/dist/index.html，请先执行 05_build_frontend.sh"
assert_under_dir "${FRONTEND_PUBLISH_DIR}" "${BOTREE_BASE_DIR}"
install -d -m 0755 "${FRONTEND_PUBLISH_DIR}"
find "${FRONTEND_PUBLISH_DIR}" -mindepth 1 -maxdepth 1 -exec rm -rf -- {} +
cp -a "${PROJECT_ROOT}/frontend/dist/." "${FRONTEND_PUBLISH_DIR}/"

log "前端发布完成: ${FRONTEND_PUBLISH_DIR}"

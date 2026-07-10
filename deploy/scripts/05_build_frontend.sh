#!/usr/bin/env bash

set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=deploy/scripts/common.sh
source "${SCRIPT_DIR}/common.sh"

load_env_files
require_commands docker

export VITE_API_BASE_URL="${VITE_API_BASE_URL:-/api}"
export VITE_APP_TITLE="${VITE_APP_TITLE:-Botree Knowledge OS}"

if command -v npm >/dev/null 2>&1; then
    (
        cd "${PROJECT_ROOT}/frontend"
        rm -rf dist
        npm ci
        npm run build
    )
else
    docker run --rm \
        -u "$(id -u):$(id -g)" \
        -v "${PROJECT_ROOT}/frontend:/workspace" \
        -w /workspace \
        -e VITE_API_BASE_URL="${VITE_API_BASE_URL}" \
        -e VITE_APP_TITLE="${VITE_APP_TITLE}" \
        "${FRONTEND_BUILD_IMAGE}" \
        sh -lc 'rm -rf dist && npm ci && npm run build'
fi

[[ -f "${PROJECT_ROOT}/frontend/dist/index.html" ]] || die "前端构建失败，未生成 dist/index.html"
log "前端构建完成"

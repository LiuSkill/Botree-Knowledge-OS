#!/usr/bin/env bash
# Botree Knowledge OS backend startup script
#
# 负责：
# 1. 从 backend 目录启动 FastAPI 服务
# 2. 固定监听 8888 端口
# 3. 便于演示环境一键启动

set -e
cd "$(dirname "$0")"
python -m app.scripts.migrate_database_on_startup
uvicorn main:app --host 0.0.0.0 --port 8888 --reload

#!/usr/bin/env sh

set -eu

cd /app

if [ "${AUTO_MIGRATE_DATABASE:-true}" = "true" ]; then
    echo "Applying database migrations..."
    alembic upgrade head
    alembic current --check-heads
    echo "Database schema is up to date."
fi

exec "$@"

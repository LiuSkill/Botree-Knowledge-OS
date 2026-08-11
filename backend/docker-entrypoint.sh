#!/usr/bin/env sh

set -eu

cd /app

if [ "${AUTO_MIGRATE_DATABASE:-true}" = "true" ]; then
    echo "Applying database migrations..."
    python -m app.scripts.migrate_database_on_startup
    echo "Database schema is up to date."
fi

exec "$@"

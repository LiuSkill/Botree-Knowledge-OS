"""后端容器启动入口测试。"""

from pathlib import Path


WORKSPACE_ROOT = Path(__file__).resolve().parents[2]
BACKEND_DOCKERFILE = WORKSPACE_ROOT / "deploy" / "docker" / "backend.Dockerfile"
BACKEND_ENTRYPOINT = WORKSPACE_ROOT / "backend" / "docker-entrypoint.sh"
API_START_SCRIPT = WORKSPACE_ROOT / "deploy" / "scripts" / "03_start_api.sh"
API_BUILD_SCRIPT = WORKSPACE_ROOT / "deploy" / "scripts" / "02_build_backend.sh"
COMMON_DEPLOY_SCRIPT = WORKSPACE_ROOT / "deploy" / "scripts" / "common.sh"


def test_backend_image_runs_database_migrations_through_a_single_entrypoint() -> None:
    """任何使用 API 镜像默认入口的部署都必须先迁移数据库再启动服务。"""

    dockerfile = BACKEND_DOCKERFILE.read_text(encoding="utf-8")
    entrypoint = BACKEND_ENTRYPOINT.read_text(encoding="utf-8")
    start_script = API_START_SCRIPT.read_text(encoding="utf-8")
    build_script = API_BUILD_SCRIPT.read_text(encoding="utf-8")
    common_script = COMMON_DEPLOY_SCRIPT.read_text(encoding="utf-8")

    assert "COPY backend/docker-entrypoint.sh /app/docker-entrypoint.sh" in dockerfile
    assert 'ENTRYPOINT ["/app/docker-entrypoint.sh"]' in dockerfile
    assert "python -m app.scripts.migrate_database_on_startup" in entrypoint
    assert entrypoint.index("python -m app.scripts.migrate_database_on_startup") < entrypoint.index('exec "$@"')
    assert "alembic upgrade head" not in start_script
    assert 'docker run --rm --entrypoint sh "${API_IMAGE}"' in build_script
    assert '[[ "${MYSQL_HOST}" == "${MYSQL_CONTAINER_NAME}" ]]' in common_script

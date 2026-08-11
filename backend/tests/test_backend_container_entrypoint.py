"""后端容器启动入口测试。"""

from pathlib import Path


WORKSPACE_ROOT = Path(__file__).resolve().parents[2]
BACKEND_DOCKERFILE = WORKSPACE_ROOT / "deploy" / "docker" / "backend.Dockerfile"
BACKEND_ENTRYPOINT = WORKSPACE_ROOT / "backend" / "docker-entrypoint.sh"
API_START_SCRIPT = WORKSPACE_ROOT / "deploy" / "scripts" / "03_start_api.sh"


def test_backend_image_runs_database_migrations_through_a_single_entrypoint() -> None:
    """任何使用 API 镜像默认入口的部署都必须先迁移数据库再启动服务。"""

    dockerfile = BACKEND_DOCKERFILE.read_text(encoding="utf-8")
    entrypoint = BACKEND_ENTRYPOINT.read_text(encoding="utf-8")
    start_script = API_START_SCRIPT.read_text(encoding="utf-8")

    assert "COPY backend/docker-entrypoint.sh /app/docker-entrypoint.sh" in dockerfile
    assert 'ENTRYPOINT ["/app/docker-entrypoint.sh"]' in dockerfile
    assert "alembic upgrade head" in entrypoint
    assert "alembic current --check-heads" in entrypoint
    assert entrypoint.index("alembic upgrade head") < entrypoint.index('exec "$@"')
    assert "alembic upgrade head" not in start_script

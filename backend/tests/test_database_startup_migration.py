"""服务启动时数据库引导测试。"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from sqlalchemy import create_engine, inspect, text


BACKEND_ROOT = Path(__file__).resolve().parents[1]


def test_empty_database_is_bootstrapped_and_stamped_to_alembic_head(tmp_path: Path) -> None:
    """空数据库必须先建立当前基线，不能直接执行首条 ALTER 迁移。"""

    database_path = tmp_path / "empty.db"
    environment = {
        **os.environ,
        "APP_ENV": "development",
        "DATABASE_URL": f"sqlite:///{database_path.as_posix()}",
        "ALLOW_SQLITE_FALLBACK": "true",
    }

    result = subprocess.run(
        [sys.executable, "-m", "app.scripts.migrate_database_on_startup"],
        cwd=BACKEND_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    engine = create_engine(environment["DATABASE_URL"])
    assert "documents" in inspect(engine).get_table_names()
    with engine.connect() as connection:
        revision = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
    assert revision == "20260806_qa_trace_events"

    second_result = subprocess.run(
        [sys.executable, "-m", "app.scripts.migrate_database_on_startup"],
        cwd=BACKEND_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert second_result.returncode == 0, second_result.stderr

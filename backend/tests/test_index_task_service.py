from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.models import Base, IndexTask
from app.services.index_task_service import IndexTaskService


def make_session() -> Session:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    return factory()


def test_list_document_tasks_only_returns_latest_attempt_per_version_and_type() -> None:
    db = make_session()
    try:
        db.add_all(
            [
                IndexTask(document_id=7, version_no=1, task_type="full_build", status="failed", progress=100),
                IndexTask(document_id=7, version_no=1, task_type="full_build", status="success", progress=100),
                IndexTask(document_id=7, version_no=1, task_type="mineru_parse", status="success", progress=100),
                IndexTask(document_id=7, version_no=2, task_type="full_build", status="failed", progress=100),
            ]
        )
        db.commit()

        tasks = IndexTaskService(db).list_document_tasks(7)

        assert [(task.version_no, task.task_type, task.status) for task in tasks] == [
            (2, "full_build", "failed"),
            (1, "mineru_parse", "success"),
            (1, "full_build", "success"),
        ]
    finally:
        db.close()


def test_mark_latest_task_success_clears_previous_parse_failure() -> None:
    db = make_session()
    try:
        task = IndexTask(
            document_id=7,
            version_no=1,
            task_type="mineru_parse",
            status="failed",
            progress=100,
            error_message="CUDA out of memory",
        )
        newer_version_task = IndexTask(
            document_id=7,
            version_no=2,
            task_type="mineru_parse",
            status="failed",
            progress=100,
            error_message="newer version failed",
        )
        db.add_all([task, newer_version_task])
        db.commit()

        IndexTaskService(db).mark_latest_task_success(
            document_id=7,
            version_no=1,
            task_type="mineru_parse",
            result={"chunk_count": 3},
        )
        db.commit()
        db.refresh(task)

        assert task.status == "success"
        assert task.progress == 100
        assert task.error_message is None
        assert task.result_json == '{"chunk_count": 3}'
        assert task.finished_at is not None
        assert newer_version_task.status == "failed"
        assert newer_version_task.error_message == "newer version failed"
    finally:
        db.close()

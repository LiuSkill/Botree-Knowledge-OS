"""多意图问答的数据会话边界。"""

from __future__ import annotations

from contextlib import contextmanager
from collections.abc import Iterator

from sqlalchemy.orm import Session, sessionmaker


class MultiIntentRepository:
    """为并发意图提供彼此隔离的数据库会话。"""

    def __init__(self, db: Session | None) -> None:
        self.db = db

    @contextmanager
    def isolated_session(self) -> Iterator[Session | None]:
        if self.db is None:
            yield None
            return

        child_db = sessionmaker(bind=self.db.get_bind(), expire_on_commit=False)()
        try:
            yield child_db
        finally:
            child_db.close()

"""User profile and avatar tests."""

from __future__ import annotations

import os
import sys
import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

BASE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE_DIR))
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-user-profile")

from app.core.exceptions import AppException  # noqa: E402
from app.core.security import hash_password, verify_password  # noqa: E402
from app.models import Base  # noqa: E402
from app.models.user import User  # noqa: E402
from app.services.auth_service import AuthService  # noqa: E402
from app.services.user_service import UserService  # noqa: E402


class FakeUploadFile:
    """用于模拟 FastAPI UploadFile 的最小对象。"""

    def __init__(self, content: bytes, filename: str = "avatar.png", content_type: str = "image/png") -> None:
        self._content = content
        self.filename = filename
        self.content_type = content_type

    async def read(self, size: int = -1) -> bytes:
        """读取上传内容。"""

        return self._content if size < 0 else self._content[:size]


class FakeMinioObject:
    """模拟 MinIO get_object 返回值。"""

    def __init__(self, content: bytes) -> None:
        self.content = content
        self.closed = False
        self.released = False

    def stream(self, _chunk_size: int):
        """按块返回对象内容。"""

        yield self.content

    def close(self) -> None:
        """关闭响应。"""

        self.closed = True

    def release_conn(self) -> None:
        """释放连接。"""

        self.released = True


class FakeMinioClient:
    """记录头像对象写入、读取和删除的假 MinIO 客户端。"""

    def __init__(self) -> None:
        self.objects: dict[tuple[str, str], tuple[bytes, str | None]] = {}
        self.removed: list[tuple[str, str]] = []

    def put_object(self, bucket: str, object_key: str, data, length: int, content_type: str | None = None) -> None:
        """保存对象内容。"""

        self.objects[(bucket, object_key)] = (data.read(length), content_type)

    def get_object(self, bucket: str, object_key: str) -> FakeMinioObject:
        """读取对象内容。"""

        return FakeMinioObject(self.objects[(bucket, object_key)][0])

    def remove_object(self, bucket: str, object_key: str) -> None:
        """删除对象。"""

        self.removed.append((bucket, object_key))
        self.objects.pop((bucket, object_key), None)


@pytest.fixture()
def db_session() -> Session:
    """创建独立内存数据库会话。"""

    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    with session_factory() as session:
        yield session
    engine.dispose()


@pytest.fixture()
def fake_settings() -> SimpleNamespace:
    """提供头像测试所需的配置对象。"""

    return SimpleNamespace(api_prefix="/api", minio_bucket="test-bucket")


def seed_user(db: Session, password: str = "OldPassword123") -> User:
    """写入测试用户。"""

    user = User(username="profile-user", password_hash=hash_password(password), real_name="Profile User", status="enabled")
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def test_current_user_response_includes_avatar_url(db_session: Session, monkeypatch: pytest.MonkeyPatch, fake_settings: SimpleNamespace) -> None:
    """当前用户信息应返回可受控读取的头像地址。"""

    monkeypatch.setattr("app.utils.user_avatar.get_settings", lambda: fake_settings)
    user = seed_user(db_session)
    user.avatar_object_key = "avatars/1/current.png"
    db_session.commit()

    profile = AuthService(db_session).to_current_user(user)

    assert profile["avatar_url"] == f"/api/users/{user.id}/avatar"
    assert profile["avatar_updated_at"] is None


def test_upload_avatar_requires_minio(db_session: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    """未启用 MinIO 时头像上传必须失败。"""

    user = seed_user(db_session)
    monkeypatch.setattr("app.services.user_service.get_minio_client", lambda: None)

    with pytest.raises(AppException, match="对象存储未启用"):
        asyncio.run(UserService(db_session).upload_own_avatar(user, FakeUploadFile(b"avatar")))


def test_upload_avatar_writes_minio_and_updates_metadata(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
    fake_settings: SimpleNamespace,
) -> None:
    """上传头像应写入 MinIO 并更新用户头像元数据。"""

    user = seed_user(db_session)
    fake_client = FakeMinioClient()
    monkeypatch.setattr("app.services.user_service.get_minio_client", lambda: fake_client)
    monkeypatch.setattr("app.services.user_service.get_settings", lambda: fake_settings)
    monkeypatch.setattr("app.utils.user_avatar.get_settings", lambda: fake_settings)

    profile = asyncio.run(UserService(db_session).upload_own_avatar(user, FakeUploadFile(b"avatar-content")))

    assert user.avatar_object_key is not None
    assert user.avatar_object_key.startswith(f"avatars/{user.id}/")
    assert fake_client.objects[(fake_settings.minio_bucket, user.avatar_object_key)] == (b"avatar-content", "image/png")
    assert user.avatar_file_name == "avatar.png"
    assert user.avatar_content_type == "image/png"
    assert profile["avatar_url"] == f"/api/users/{user.id}/avatar"


def test_avatar_stream_returns_minio_object_for_self(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
    fake_settings: SimpleNamespace,
) -> None:
    """用户本人应可读取自己的头像对象。"""

    user = seed_user(db_session)
    user.avatar_object_key = f"avatars/{user.id}/avatar.png"
    user.avatar_content_type = "image/png"
    db_session.commit()
    fake_client = FakeMinioClient()
    fake_client.objects[(fake_settings.minio_bucket, user.avatar_object_key)] = (b"avatar-content", "image/png")
    monkeypatch.setattr("app.services.user_service.get_minio_client", lambda: fake_client)
    monkeypatch.setattr("app.services.user_service.get_settings", lambda: fake_settings)

    avatar = UserService(db_session).open_avatar_stream(user.id, user)

    assert avatar["content_type"] == "image/png"
    assert b"".join(avatar["content"]) == b"avatar-content"


def test_delete_avatar_clears_metadata_and_removes_object(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
    fake_settings: SimpleNamespace,
) -> None:
    """删除头像应移除 MinIO 对象并清空用户头像元数据。"""

    user = seed_user(db_session)
    user.avatar_object_key = f"avatars/{user.id}/avatar.png"
    user.avatar_file_name = "avatar.png"
    user.avatar_content_type = "image/png"
    db_session.commit()
    fake_client = FakeMinioClient()
    fake_client.objects[(fake_settings.minio_bucket, user.avatar_object_key)] = (b"avatar-content", "image/png")
    monkeypatch.setattr("app.services.user_service.get_minio_client", lambda: fake_client)
    monkeypatch.setattr("app.services.user_service.get_settings", lambda: fake_settings)

    profile = UserService(db_session).delete_own_avatar(user)

    assert profile["avatar_url"] is None
    assert user.avatar_object_key is None
    assert fake_client.removed == [(fake_settings.minio_bucket, f"avatars/{user.id}/avatar.png")]


def test_change_password_rejects_invalid_current_password(db_session: Session) -> None:
    """原密码错误时禁止修改密码。"""

    user = seed_user(db_session)

    with pytest.raises(AppException, match="当前密码错误"):
        UserService(db_session).change_own_password(user, "WrongPassword", "NewPassword123")


def test_change_password_updates_hash(db_session: Session) -> None:
    """原密码正确时应更新密码哈希。"""

    user = seed_user(db_session)

    UserService(db_session).change_own_password(user, "OldPassword123", "NewPassword123")

    assert verify_password("NewPassword123", user.password_hash)
    assert not verify_password("OldPassword123", user.password_hash)

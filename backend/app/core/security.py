"""
Security Utilities

负责：
1. 密码哈希与校验
2. JWT Token 生成与解析
3. 为认证 Service 提供安全基础能力
"""

import base64
import hashlib
import hmac
import os
from datetime import datetime, timedelta, timezone
from typing import Any

import jwt

from app.core.config import get_settings


def hash_password(password: str) -> str:
    """
    生成密码哈希

    参数:
        password: 明文密码

    返回:
        带盐的 PBKDF2 哈希字符串。
    """

    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 120_000)
    return f"pbkdf2_sha256${base64.b64encode(salt).decode()}${base64.b64encode(digest).decode()}"


def verify_password(password: str, password_hash: str) -> bool:
    """
    校验密码

    参数:
        password: 用户提交的明文密码
        password_hash: 数据库保存的哈希

    返回:
        密码是否匹配。
    """

    try:
        algorithm, salt_text, digest_text = password_hash.split("$", 2)
        if algorithm != "pbkdf2_sha256":
            return False
        salt = base64.b64decode(salt_text)
        expected = base64.b64decode(digest_text)
        actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 120_000)
        return hmac.compare_digest(actual, expected)
    except Exception:
        return False


def create_access_token(subject: str, claims: dict[str, Any] | None = None) -> str:
    """
    创建 JWT 访问令牌

    参数:
        subject: 用户唯一标识
        claims: 附加声明

    返回:
        JWT token 字符串。
    """

    settings = get_settings()
    now = datetime.now(timezone.utc)
    payload: dict[str, Any] = {
        "sub": subject,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=settings.access_token_expire_minutes)).timestamp()),
    }
    if claims:
        payload.update(claims)
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> dict[str, Any]:
    """
    解析 JWT 访问令牌

    参数:
        token: 前端传入的 Bearer Token

    返回:
        JWT 载荷。
    """

    settings = get_settings()
    return jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])

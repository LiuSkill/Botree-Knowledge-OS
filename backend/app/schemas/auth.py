"""
Auth Schemas

负责：
1. 登录请求和 Token 响应建模
2. 当前用户响应建模
3. 支持认证 API Swagger 说明
"""

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    """
    登录请求

    职责：
    - 接收用户名和密码
    - 用于 POST /api/auth/login
    """

    username: str = Field(..., description="用户名")
    password: str = Field(..., description="密码")


class TokenResponse(BaseModel):
    """
    Token 响应

    职责：
    - 返回 JWT 访问令牌
    - 返回 token 类型和当前用户
    """

    access_token: str = Field(..., description="访问令牌")
    token_type: str = Field(default="bearer", description="Token 类型")
    user: dict = Field(..., description="当前用户信息")

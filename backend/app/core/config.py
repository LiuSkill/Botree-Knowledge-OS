"""
Botree Configuration

负责：
1. 从 .env 读取运行配置
2. 管理数据库、JWT、Redis、MinIO、Milvus、MinerU 和模型参数
3. 避免在业务代码中出现硬编码配置
"""

import os
from functools import lru_cache
from pathlib import Path
from urllib.parse import quote_plus

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    系统运行配置

    职责：
    - 读取环境变量和 .env 文件
    - 为数据库、安全认证和文件上传提供统一配置
    - 为 Redis、MinIO、Milvus、MinerU 和 LLM 客户端提供扩展入口
    """

    app_name: str = Field(default="Botree Knowledge OS", alias="APP_NAME")
    app_env: str = Field(default="development", alias="APP_ENV")
    debug: bool = Field(default=True, alias="DEBUG")
    api_prefix: str = Field(default="/api", alias="API_PREFIX")
    host: str = Field(default="0.0.0.0", alias="HOST")
    port: int = Field(default=8888, alias="PORT")

    database_url: str | None = Field(default=None, alias="DATABASE_URL")
    mysql_host: str | None = Field(default=None, alias="MYSQL_HOST")
    mysql_port: int = Field(default=3306, alias="MYSQL_PORT")
    mysql_database: str | None = Field(default=None, alias="MYSQL_DATABASE")
    mysql_user: str | None = Field(default=None, alias="MYSQL_USER")
    mysql_password: str | None = Field(default=None, alias="MYSQL_PASSWORD")

    redis_host: str | None = Field(default=None, alias="REDIS_HOST")
    redis_port: int = Field(default=6379, alias="REDIS_PORT")
    redis_password: str | None = Field(default=None, alias="REDIS_PASSWORD")
    redis_db: int = Field(default=0, alias="REDIS_DB")
    rq_queue_name: str = Field(default="botree-index", alias="RQ_QUEUE_NAME")

    minio_endpoint: str | None = Field(default=None, alias="MINIO_ENDPOINT")
    minio_access_key: str | None = Field(default=None, alias="MINIO_ACCESS_KEY")
    minio_secret_key: str | None = Field(default=None, alias="MINIO_SECRET_KEY")
    minio_bucket: str | None = Field(default=None, alias="MINIO_BUCKET")
    minio_secure: bool = Field(default=False, alias="MINIO_SECURE")

    milvus_host: str | None = Field(default=None, alias="MILVUS_HOST")
    milvus_port: int = Field(default=19530, alias="MILVUS_PORT")
    milvus_collection: str = Field(default="botree_collection", alias="MILVUS_COLLECTION")
    embedding_dim: int = Field(default=1024, alias="EMBEDDING_DIM")

    mineru_base_url: str | None = Field(default=None, alias="MINERU_BASE_URL")
    mineru_parse_path: str = Field(default="/file_parse", alias="MINERU_PARSE_PATH")
    mineru_task_submit_path: str = Field(default="/tasks", alias="MINERU_TASK_SUBMIT_PATH")
    mineru_task_timeout_seconds: int = Field(default=300, alias="MINERU_TASK_TIMEOUT_SECONDS")
    mineru_poll_interval_seconds: int = Field(default=5, alias="MINERU_POLL_INTERVAL_SECONDS")
    mineru_http_timeout_seconds: int = Field(default=30, alias="MINERU_HTTP_TIMEOUT_SECONDS")
    mineru_output_host_dir: str = Field(default="storage/mineru-output", alias="MINERU_OUTPUT_HOST_DIR")
    mineru_output_container_dir: str = Field(default="/workspace/output", alias="MINERU_OUTPUT_CONTAINER_DIR")
    libreoffice_binary: str = Field(default="soffice", alias="LIBREOFFICE_BINARY")
    libreoffice_timeout_seconds: int = Field(default=180, alias="LIBREOFFICE_TIMEOUT_SECONDS")
    libreoffice_work_dir: str = Field(default="storage/derived", alias="LIBREOFFICE_WORK_DIR")

    openai_compatible_base_url: str | None = Field(default=None, alias="OPENAI_COMPATIBLE_BASE_URL")
    openai_api_key: str | None = Field(default=None, alias="OPENAI_API_KEY")
    llm_provider: str = Field(default="openai_compatible", alias="LLM_PROVIDER")
    llm_base_url: str | None = Field(default=None, alias="LLM_BASE_URL")
    llm_api_key: str | None = Field(default=None, alias="LLM_API_KEY")
    llm_model: str = Field(default="qwen3.7-max", alias="LLM_MODEL")
    llm_timeout_seconds: int = Field(default=60, alias="LLM_TIMEOUT_SECONDS")
    intent_llm_model: str = Field(default="qwen3.5-flash", alias="INTENT_LLM_MODEL")
    planner_llm_model: str = Field(default="qwen3.5-flash", alias="PLANNER_LLM_MODEL")
    evidence_judge_fast_model: str = Field(default="qwen3.5-flash", alias="EVIDENCE_JUDGE_FAST_MODEL")
    evidence_judge_model: str = Field(default="qwen3.5-plus", alias="EVIDENCE_JUDGE_MODEL")
    evidence_judge_timeout_seconds: int = Field(default=15, alias="EVIDENCE_JUDGE_TIMEOUT_SECONDS")
    answer_llm_model: str = Field(default="qwen3.5-plus", alias="ANSWER_LLM_MODEL")
    analysis_llm_model: str = Field(default="qwen3.7-max", alias="ANALYSIS_LLM_MODEL")
    vision_llm_provider: str = Field(default="qwen_api", alias="VISION_LLM_PROVIDER")
    vision_llm_base_url: str | None = Field(default=None, alias="VISION_LLM_BASE_URL")
    vision_llm_api_key: str | None = Field(default=None, alias="VISION_LLM_API_KEY")
    vision_llm_model: str = Field(default="qwen3.5-plus", alias="VISION_LLM_MODEL")
    vision_llm_timeout_seconds: int = Field(default=90, alias="VISION_LLM_TIMEOUT_SECONDS")
    vision_llm_max_images: int = Field(default=2, alias="VISION_LLM_MAX_IMAGES")
    vision_llm_max_image_bytes: int = Field(default=8 * 1024 * 1024, alias="VISION_LLM_MAX_IMAGE_BYTES")
    embedding_provider: str = Field(default="local", alias="EMBEDDING_PROVIDER")
    embedding_model: str | None = Field(default=None, alias="EMBEDDING_MODEL")
    embedding_device: str = Field(default="cpu", alias="EMBEDDING_DEVICE")
    embedding_batch_size: int = Field(default=8, alias="EMBEDDING_BATCH_SIZE")
    embedding_timeout_seconds: int = Field(default=60, alias="EMBEDDING_TIMEOUT_SECONDS")

    jwt_secret_key: str = Field(alias="JWT_SECRET_KEY")
    jwt_algorithm: str = Field(default="HS256", alias="JWT_ALGORITHM")
    access_token_expire_minutes: int = Field(default=1440, alias="ACCESS_TOKEN_EXPIRE_MINUTES")

    upload_dir: str = Field(default="storage/uploads", alias="UPLOAD_DIR")
    page_index_dir: str = Field(default="storage/page_index", alias="PAGE_INDEX_DIR")
    ripgrep_binary: str = Field(default="rg", alias="RIPGREP_BINARY")
    retrieval_trace_enabled: bool = Field(default=True, alias="RETRIEVAL_TRACE_ENABLED")
    project_chat_include_industry_knowledge: bool = Field(
        default=False,
        alias="PROJECT_CHAT_INCLUDE_INDUSTRY_KNOWLEDGE",
    )
    default_admin_username: str = Field(default="admin", alias="DEFAULT_ADMIN_USERNAME")
    default_admin_password: str | None = Field(default=None, alias="DEFAULT_ADMIN_PASSWORD")
    default_admin_real_name: str = Field(default="系统管理员", alias="DEFAULT_ADMIN_REAL_NAME")

    model_config = SettingsConfigDict(
        env_file=(".env", "backend/.env"),
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    @property
    def backend_root(self) -> Path:
        """
        获取后端工作目录绝对路径。

        返回：
            `backend/` 目录对应的绝对路径。
        """

        return Path(__file__).resolve().parents[2]

    @property
    def workspace_root(self) -> Path:
        """
        获取项目根目录绝对路径。

        返回：
            仓库根目录绝对路径。
        """

        return self.backend_root.parent

    def resolve_local_path(self, path_value: str | Path) -> Path:
        """
        把数据库中的本地相对路径解析为稳定的绝对路径。

        参数:
            path_value: 数据库存储路径或本地文件路径。

        返回：
            适用于 API、Worker 和脚本环境的绝对路径。
        """

        path = Path(path_value)
        if path.is_absolute():
            return path

        if path.parts and path.parts[0].lower() == "backend":
            return (self.workspace_root / path).resolve(strict=False)
        return (self.backend_root / path).resolve(strict=False)

    def to_relative_local_path(self, path_value: str | Path) -> str:
        """
        将本地绝对路径回写为相对 `backend/` 的存储路径。

        参数:
            path_value: 绝对路径或相对路径。

        返回：
            优先返回相对 `backend/` 的路径，便于跨进程复用。
        """

        resolved_path = self.resolve_local_path(path_value)
        try:
            return str(resolved_path.relative_to(self.backend_root))
        except ValueError:
            return str(resolved_path)

    @field_validator("jwt_secret_key")
    @classmethod
    def validate_jwt_secret_key(cls, value: str) -> str:
        """
        校验 JWT 签名密钥强度。

        参数:
            value: 从 .env 读取的 JWT_SECRET_KEY。

        返回:
            已去除首尾空白的密钥。
        """

        normalized = value.strip()
        if len(normalized.encode("utf-8")) < 32:
            raise ValueError("JWT_SECRET_KEY长度不能低于32字节，请在.env中配置随机强密钥")
        return normalized

    @property
    def effective_database_url(self) -> str:
        """
        获取最终数据库连接串

        返回:
            优先使用 DATABASE_URL；未配置时根据 MYSQL_* 变量拼接 MySQL URL；
            如果二者都未提供，则退回本地 SQLite，方便自动化测试和离线演示。
        """

        if self.database_url:
            return self.database_url
        if self.mysql_host and self.mysql_database and self.mysql_user is not None:
            password = quote_plus(self.mysql_password or "")
            user = quote_plus(self.mysql_user)
            return (
                f"mysql+pymysql://{user}:{password}@{self.mysql_host}:"
                f"{self.mysql_port}/{self.mysql_database}?charset=utf8mb4"
            )
        return "sqlite:///./botree_knowledge.db"

    @property
    def mysql_server_url(self) -> str | None:
        """
        获取不带数据库名的 MySQL 服务连接串

        返回:
            用于非破坏性创建数据库的服务级连接串；非 MySQL 配置时返回 None。
        """

        if not (self.mysql_host and self.mysql_user is not None):
            return None
        password = quote_plus(self.mysql_password or "")
        user = quote_plus(self.mysql_user)
        return f"mysql+pymysql://{user}:{password}@{self.mysql_host}:{self.mysql_port}?charset=utf8mb4"

    @property
    def mineru_parse_url(self) -> str | None:
        """
        获取 MinerU 文件解析接口地址

        返回:
            MinerU 完整解析 URL；未配置 MinerU 时返回 None，由解析服务使用本地真实解析器。
        """

        if not self.mineru_base_url:
            return None
        return f"{self.mineru_base_url.rstrip('/')}/{self.mineru_parse_path.lstrip('/')}"

    @property
    def mineru_enabled(self) -> bool:
        """
        鍒ゆ柇鏄惁閰嶇疆 MinerU 寮哄埗瑙ｆ瀽鏈嶅姟銆?
        杩斿洖:
            True 琛ㄧず褰撳墠鐜宸插惎鐢?MinerU锛沝alse 琛ㄧず鍏佽浣跨敤鏈湴鍏滃簳瑙ｆ瀽鍣ㄣ€?
        """

        return bool(self.mineru_base_url)

    @property
    def mineru_output_host_path(self) -> Path:
        """
        获取 MinerU Docker 共享卷在宿主机上的输出根目录。
        返回:
            供 API 和 Worker 读取解析产物的宿主机绝对路径。
        """

        return self.resolve_local_path(self.mineru_output_host_dir)

    def ensure_mineru_output_mapping_ready(self) -> Path:
        """
        校验并准备 MinerU Docker 共享卷宿主机输出目录。
        返回:
            已存在且可写的宿主机输出根目录。
        """

        if not self.mineru_enabled:
            raise ValueError("未启用 MinerU，不能校验输出映射目录")
        if not self.mineru_output_container_dir.strip():
            raise ValueError("已配置 MINERU_BASE_URL，但缺少 MINERU_OUTPUT_CONTAINER_DIR")

        host_path = self.mineru_output_host_path
        host_path.mkdir(parents=True, exist_ok=True)
        if not host_path.is_dir():
            raise ValueError(f"MinerU 输出宿主机目录不是有效目录: {host_path}")
        if not os.access(host_path, os.W_OK):
            raise ValueError(f"MinerU 输出宿主机目录不可写: {host_path}")
        return host_path

    @property
    def mineru_task_submit_url(self) -> str | None:
        """
        鑾峰彇 MinerU 寮傛浠诲姟鎻愪氦鎺ュ彛鍦板潃銆?
        杩斿洖:
            `/tasks` 瀹屾暣 URL锛涙湭閰嶇疆 MinerU 鏃惰繑鍥?None銆?
        """

        if not self.mineru_base_url:
            return None
        return f"{self.mineru_base_url.rstrip('/')}/{self.mineru_task_submit_path.lstrip('/')}"

    def mineru_task_status_url(self, task_id: str) -> str | None:
        """
        鎷兼帴 MinerU 浠诲姟鐘舵€佹煡璇㈠湴鍧€銆?
        鍙傛暟:
            task_id: MinerU 浠诲姟ID銆?
        杩斿洖:
            `/tasks/{task_id}` 瀹屾暣 URL锛涙湭閰嶇疆 MinerU 鏃惰繑鍥?None銆?
        """

        if not self.mineru_base_url:
            return None
        return f"{self.mineru_base_url.rstrip('/')}/tasks/{task_id}"

    def mineru_task_result_url(self, task_id: str) -> str | None:
        """
        鎷兼帴 MinerU 浠诲姟缁撴灉鏌ヨ鍦板潃銆?
        鍙傛暟:
            task_id: MinerU 浠诲姟ID銆?
        杩斿洖:
            `/tasks/{task_id}/result` 瀹屾暣 URL锛涙湭閰嶇疆 MinerU 鏃惰繑鍥?None銆?
        """

        if not self.mineru_base_url:
            return None
        return f"{self.mineru_base_url.rstrip('/')}/tasks/{task_id}/result"

    @property
    def minio_enabled(self) -> bool:
        """
        判断是否启用 MinIO 对象存储。

        返回:
            True 表示 MinIO 配置完整，上传服务会同步写入对象存储。
        """

        return bool(self.minio_endpoint and self.minio_access_key and self.minio_secret_key and self.minio_bucket)

    @property
    def redis_url(self) -> str | None:
        """
        获取 Redis 连接地址。

        返回:
            配置 Redis Host 时返回 redis:// URL；未配置时返回 None，调用方应使用同步降级逻辑。
        """

        if not self.redis_host:
            return None
        password = f":{quote_plus(self.redis_password)}@" if self.redis_password else ""
        return f"redis://{password}{self.redis_host}:{self.redis_port}/{self.redis_db}"

    @property
    def milvus_enabled(self) -> bool:
        """
        判断是否启用 Milvus 向量检索。

        返回:
            True 表示配置了 Milvus Host，索引和检索可连接向量库。
        """

        return bool(self.milvus_host)

    @property
    def upload_path(self) -> Path:
        """
        获取上传目录的 Path 对象

        返回:
            上传目录路径，业务层可直接用于保存文件。
        """

        return self.resolve_local_path(self.upload_dir)

    @property
    def page_index_path(self) -> Path:
        """
        获取 PageIndex 本地文本镜像目录。

        返回:
            用于 ripgrep 精确检索的页面文本根目录。
        """

        return self.resolve_local_path(self.page_index_dir)

    @property
    def libreoffice_work_path(self) -> Path:
        """
        获取 LibreOffice 工作目录和派生资产根目录。

        返回:
            用于保存转换 PDF、MinerU 原始结果和预览图片的本地目录。
        """

        return self.resolve_local_path(self.libreoffice_work_dir)


@lru_cache
def get_settings() -> Settings:
    """
    获取全局配置单例

    返回:
        Settings 实例，避免重复读取环境配置。
    """

    return Settings()

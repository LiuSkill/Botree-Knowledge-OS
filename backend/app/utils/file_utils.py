"""
File Utilities

负责：
1. 生成安全文件名
2. 判断文件类型
3. 提供文件读取辅助能力
"""

import re
import uuid
from pathlib import Path


def safe_storage_name(file_name: str) -> str:
    """
    生成安全存储文件名

    参数:
        file_name: 原始文件名

    返回:
        带 UUID 前缀的安全文件名。
    """

    suffix = Path(file_name).suffix.lower()
    stem = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff._-]+", "_", Path(file_name).stem)[:80]
    return f"{uuid.uuid4().hex}_{stem}{suffix}"


def file_type(file_name: str) -> str:
    """
    获取文件类型

    参数:
        file_name: 文件名

    返回:
        不带点的文件扩展名。
    """

    suffix = Path(file_name).suffix.lower().lstrip(".")
    return suffix or "unknown"

"""CLI for importing a local project directory into project documents."""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPO_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.core.exceptions import AppException  # noqa: E402
from app.core.security_levels import DEFAULT_SECURITY_LEVEL  # noqa: E402
from app.services.project_directory_import_service import ProjectDirectoryImportService  # noqa: E402

logger = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="导入本地项目目录，仅建档保存文件，不触发解析或索引。")
    parser.add_argument("--source", required=True, help="源目录，例如 E:\\download\\BC2413 西班牙LFP项目")
    parser.add_argument("--project-code", default="BC2413", help="项目编号")
    parser.add_argument("--project-name", default="西班牙LFP项目", help="项目名称")
    parser.add_argument("--project-short-name", default=None, help="项目简称")
    parser.add_argument("--client", default="待补充", help="客户名称占位值")
    parser.add_argument("--manager", default="待补充", help="负责人占位值")
    parser.add_argument("--description", default=None, help="项目简介")
    parser.add_argument("--status", default="进行中", help="项目状态")
    parser.add_argument("--operator", default="admin", help="导入操作人用户名")
    parser.add_argument("--file-scope", choices=("knowledge", "parsable", "all"), default="knowledge", help="导入文件范围")
    parser.add_argument("--security-level", default=DEFAULT_SECURITY_LEVEL, help="项目和导入文档密级")
    parser.add_argument("--resume-project-id", type=int, default=None, help="继续导入已有项目 ID")
    parser.add_argument("--limit", type=int, default=None, help="仅导入前 N 个纳入范围文件，用于小批量验证")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="只生成扫描报告，不写数据库")
    mode.add_argument("--commit", action="store_true", help="执行真实导入")
    return parser


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    parser = build_parser()
    args = parser.parse_args(argv)
    dry_run = not args.commit

    try:
        from app.core.database import SessionLocal, init_database

        if not dry_run:
            init_database()
        with SessionLocal() as db:
            report = ProjectDirectoryImportService(db).import_directory(
                source=args.source,
                operator_username=args.operator,
                project_code=args.project_code,
                project_name=args.project_name,
                project_short_name=args.project_short_name,
                client=args.client,
                manager=args.manager,
                description=args.description,
                status=args.status,
                security_level=args.security_level,
                file_scope=args.file_scope,
                dry_run=dry_run,
                resume_project_id=args.resume_project_id,
                limit=args.limit,
            )
        logger.info("项目目录导入报告:\n%s", json.dumps(report, ensure_ascii=False, indent=2))
        return 0
    except AppException as exc:
        logger.error("项目目录导入失败: %s", exc.message)
        return 1
    except Exception:
        logger.exception("项目目录导入出现未预期异常")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

"""CLI for removing duplicate documents created by project directory imports."""

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
from app.services.project_directory_import_service import ProjectDirectoryImportService  # noqa: E402

logger = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="清理项目目录导入产生的重复内容文档，默认仅预览。",
    )
    parser.add_argument("--project-id", required=True, type=int, help="要清理的项目 ID")
    parser.add_argument("--operator", default="admin", help="执行清理的操作人用户名")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="只生成重复数据报告，不修改数据库")
    mode.add_argument("--commit", action="store_true", help="执行清理（物理删除重复文档及关联数据）")
    return parser


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    args = build_parser().parse_args(argv)
    try:
        from app.core.database import SessionLocal

        with SessionLocal() as db:
            report = ProjectDirectoryImportService(db).remove_duplicate_imports(
                project_id=args.project_id,
                operator_username=args.operator,
                dry_run=not args.commit,
            )
        logger.info("项目导入重复数据清理报告:\n%s", json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if report["failed_document_count"] == 0 else 2
    except AppException as exc:
        logger.error("项目导入重复数据清理失败: %s", exc.message)
        return 1
    except Exception:
        logger.exception("项目导入重复数据清理出现未预期异常")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

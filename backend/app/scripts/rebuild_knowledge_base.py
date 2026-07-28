"""发布前离线执行知识库原地完整重建。"""

import argparse
import logging

from app.core.database import SessionLocal
from app.services.knowledge_base_rebuild_service import KnowledgeBaseRebuildService


def main() -> None:
    parser = argparse.ArgumentParser(description="原地完整重建指定知识库")
    parser.add_argument("knowledge_base_id", type=int)
    parser.add_argument("--resume", action="store_true", help="跳过当前版本和索引代际已经发布的文档")
    args = parser.parse_args()
    with SessionLocal() as db:
        KnowledgeBaseRebuildService(db).rebuild(args.knowledge_base_id, resume=args.resume)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()

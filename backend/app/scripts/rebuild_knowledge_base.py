"""发布前离线执行知识库原地完整重建。"""

import argparse
import logging

from app.core.database import SessionLocal
from app.services.knowledge_base_rebuild_service import KnowledgeBaseRebuildService


def main() -> None:
    parser = argparse.ArgumentParser(description="原地完整重建指定知识库")
    parser.add_argument("knowledge_base_id", type=int)
    args = parser.parse_args()
    with SessionLocal() as db:
        KnowledgeBaseRebuildService(db).rebuild(args.knowledge_base_id)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()

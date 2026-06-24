"""BEIR dataset download and loading helpers."""

from __future__ import annotations

import logging
from pathlib import Path

from eval.beir.types import BeirCorpus, BeirQrels, BeirQueries

logger = logging.getLogger(__name__)

BEIR_DATASET_BASE_URL = "https://public.ukp.informatik.tu-darmstadt.de/thakur/BEIR/datasets"


def load_beir_dataset(data_dir: Path, dataset: str, split: str = "test", download: bool = True) -> tuple[BeirCorpus, BeirQueries, BeirQrels, Path]:
    """
    Load a BEIR dataset from local disk, downloading it first when necessary.

    BEIR 原始 qrels/corpus/queries 格式由官方 GenericDataLoader 解析，避免手写
    jsonl/tsv 解析逻辑偏离 BEIR 评测约定。
    """

    dataset_path = ensure_dataset(data_dir, dataset, download=download)
    try:
        from beir.datasets.data_loader import GenericDataLoader
    except ImportError as exc:
        raise RuntimeError("缺少 beir 依赖，请先执行: python -m pip install -r backend/requirements.txt") from exc

    logger.info("加载BEIR数据集: dataset=%s split=%s path=%s", dataset, split, dataset_path)
    corpus, queries, qrels = GenericDataLoader(data_folder=str(dataset_path)).load(split=split)
    logger.info(
        "BEIR数据集加载完成: dataset=%s corpus=%s queries=%s qrels_queries=%s",
        dataset,
        len(corpus),
        len(queries),
        len(qrels),
    )
    return corpus, queries, qrels, dataset_path


def ensure_dataset(data_dir: Path, dataset: str, download: bool = True) -> Path:
    """Return a local BEIR dataset path, downloading the zip if needed."""

    data_dir.mkdir(parents=True, exist_ok=True)
    dataset_path = data_dir / dataset
    if _is_beir_dataset_ready(dataset_path):
        return dataset_path
    if not download:
        raise FileNotFoundError(f"BEIR 数据集不存在或不完整: {dataset_path}")

    try:
        from beir import util
    except ImportError as exc:
        raise RuntimeError("缺少 beir 依赖，无法下载数据集") from exc

    url = f"{BEIR_DATASET_BASE_URL}/{dataset}.zip"
    logger.info("下载BEIR数据集: dataset=%s url=%s output_dir=%s", dataset, url, data_dir)
    downloaded_path = Path(util.download_and_unzip(url, str(data_dir)))
    if not _is_beir_dataset_ready(downloaded_path):
        raise FileNotFoundError(f"BEIR 数据集下载后结构不完整: {downloaded_path}")
    return downloaded_path


def _is_beir_dataset_ready(dataset_path: Path) -> bool:
    """Check the standard BEIR files expected by GenericDataLoader."""

    return (
        dataset_path.exists()
        and (dataset_path / "corpus.jsonl").exists()
        and (dataset_path / "queries.jsonl").exists()
        and (dataset_path / "qrels").exists()
    )

"""Logging setup for BEIR evaluation scripts."""

from __future__ import annotations

import logging
from pathlib import Path


LOG_FORMAT = "%(asctime)s %(levelname)s [%(name)s] %(message)s"


def setup_logging(report_dir: Path, verbose: bool = False) -> Path:
    """Configure console and file logging for an evaluation run."""

    report_dir.mkdir(parents=True, exist_ok=True)
    log_path = report_dir / "beir_eval.log"
    root = logging.getLogger()
    root.setLevel(logging.DEBUG if verbose else logging.INFO)
    root.handlers.clear()

    formatter = logging.Formatter(LOG_FORMAT)
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setFormatter(formatter)

    root.addHandler(console_handler)
    root.addHandler(file_handler)
    return log_path

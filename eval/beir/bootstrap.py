"""Runtime path bootstrap for standalone BEIR scripts."""

from __future__ import annotations

import sys
from pathlib import Path


WORKSPACE_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = WORKSPACE_ROOT / "backend"


def ensure_backend_path() -> None:
    """Ensure backend/app can be imported when running from repository root."""

    backend_path = str(BACKEND_ROOT)
    if backend_path not in sys.path:
        sys.path.insert(0, backend_path)

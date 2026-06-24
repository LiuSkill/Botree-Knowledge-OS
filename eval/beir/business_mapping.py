"""Business document mapping helpers for BEIR evaluation."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path
from typing import Iterable

from eval.beir.bootstrap import WORKSPACE_ROOT


@dataclass(frozen=True)
class BusinessDocMapping:
    """Map one BEIR corpus doc to one business document/chunk."""

    dataset: str
    split: str
    beir_doc_id: str
    business_document_id: int
    business_chunk_id: int
    project_id: int
    title: str
    text_hash: str

    @classmethod
    def from_dict(cls, payload: dict) -> "BusinessDocMapping":
        """Create a mapping row from JSON."""

        return cls(
            dataset=str(payload["dataset"]),
            split=str(payload.get("split") or "test"),
            beir_doc_id=str(payload["beir_doc_id"]),
            business_document_id=int(payload["business_document_id"]),
            business_chunk_id=int(payload["business_chunk_id"]),
            project_id=int(payload["project_id"]),
            title=str(payload.get("title") or ""),
            text_hash=str(payload.get("text_hash") or ""),
        )

    def to_dict(self) -> dict:
        """Serialize a mapping row."""

        return asdict(self)


class BusinessDocIdMapper:
    """Resolve real RAG evidence IDs back to BEIR doc IDs."""

    def __init__(self, rows: Iterable[BusinessDocMapping]) -> None:
        self.rows = list(rows)
        self.by_chunk_id = {row.business_chunk_id: row for row in self.rows}
        self.by_document_id = {row.business_document_id: row for row in self.rows}
        self.by_beir_doc_id = {row.beir_doc_id: row for row in self.rows}

    def resolve(self, document_id: int | None, chunk_id: int | None) -> BusinessDocMapping | None:
        """Resolve by chunk first, then document as fallback."""

        if chunk_id is not None:
            row = self.by_chunk_id.get(int(chunk_id))
            if row is not None:
                return row
        if document_id is not None:
            return self.by_document_id.get(int(document_id))
        return None

    def __len__(self) -> int:
        return len(self.rows)


def mapping_path(dataset: str) -> Path:
    """Return the canonical mapping file path for a dataset."""

    return WORKSPACE_ROOT / "eval" / "beir" / "results" / dataset / "doc_id_mapping.jsonl"


def compute_text_hash(title: str, text: str) -> str:
    """Hash title + text for idempotent business import checks."""

    normalized = f"{title or ''}\n\n{text or ''}".strip()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def load_doc_id_mapping(dataset: str, split: str | None = None, path: Path | None = None) -> BusinessDocIdMapper:
    """Load BEIR business mapping JSONL."""

    resolved_path = path or mapping_path(dataset)
    if not resolved_path.exists():
        return BusinessDocIdMapper([])
    rows: list[BusinessDocMapping] = []
    with resolved_path.open("r", encoding="utf-8") as file:
        for line in file:
            line = line.strip()
            if not line:
                continue
            row = BusinessDocMapping.from_dict(json.loads(line))
            if split is not None and row.split != split:
                continue
            rows.append(row)
    return BusinessDocIdMapper(rows)


def write_doc_id_mapping(path: Path, rows: Iterable[BusinessDocMapping]) -> None:
    """Write mapping rows to JSONL."""

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as file:
        for row in rows:
            file.write(json.dumps(row.to_dict(), ensure_ascii=False) + "\n")

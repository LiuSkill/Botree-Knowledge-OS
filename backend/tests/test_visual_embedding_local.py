from __future__ import annotations

from types import SimpleNamespace

import torch
from PIL import Image

from app.services import visual_embedding_local


def test_local_visual_embedding_uses_official_embedder_and_batches(monkeypatch) -> None:
    calls: list[list[dict[str, object]]] = []
    constructor_kwargs: dict[str, object] = {}

    class FakeEmbedder:
        def __init__(self, **kwargs: object) -> None:
            constructor_kwargs.update(kwargs)

        def process(self, inputs: list[dict[str, object]]) -> torch.Tensor:
            calls.append(inputs)
            rows = [[float(len(calls)), float(index + 1), 9.0] for index in range(len(inputs))]
            return torch.tensor(rows)

    monkeypatch.setattr(
        visual_embedding_local,
        "_load_official_embedder_class",
        lambda _model_name: FakeEmbedder,
    )
    monkeypatch.setattr(torch.cuda, "is_available", lambda: False)

    model = visual_embedding_local.LocalQwenVLVisualEmbedding(
        "Qwen/Qwen3-VL-Embedding-2B",
        device="cuda",
        batch_size=2,
        dimension=2,
    )
    image = Image.new("RGB", (1, 1))

    vectors = model.encode(["query", image, "second batch"])

    assert constructor_kwargs["model_name_or_path"] == "Qwen/Qwen3-VL-Embedding-2B"
    assert calls == [
        [{"text": "query"}, {"image": image}],
        [{"text": "second batch"}],
    ]
    assert len(vectors) == 3
    assert all(len(vector) == 2 for vector in vectors)
    assert model.device == "cpu"


def test_load_official_embedder_class_from_local_model_repository(tmp_path, monkeypatch) -> None:
    script_path = tmp_path / "scripts" / "qwen3_vl_embedding.py"
    script_path.parent.mkdir()
    script_path.write_text("class Qwen3VLEmbedder:\n    pass\n", encoding="utf-8")

    embedder_class = visual_embedding_local._load_official_embedder_class(str(tmp_path))

    assert embedder_class.__name__ == "Qwen3VLEmbedder"


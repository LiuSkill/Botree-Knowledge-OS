import builtins
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services import embedding_local


def test_local_embedding_falls_back_when_sentence_transformers_import_fails(monkeypatch):
    original_import = builtins.__import__
    fallback_called = {"value": False}

    def fake_import(name, *args, **kwargs):
        if name == "sentence_transformers":
            raise ImportError("broken sentence-transformers")
        return original_import(name, *args, **kwargs)

    def fake_load_transformers(self):
        fallback_called["value"] = True
        self.auto_model = object()

    monkeypatch.setattr(builtins, "__import__", fake_import)
    monkeypatch.setattr(embedding_local.LocalQwenEmbedding, "_resolve_device", lambda self, requested: "cuda")
    monkeypatch.setattr(embedding_local.LocalQwenEmbedding, "_load_transformers_model_with_fallback", fake_load_transformers)

    embedding_local.LocalQwenEmbedding(str(Path(".")), "cuda", 1, 1024)
    assert fallback_called["value"] is True


def test_local_embedding_requires_gpu(monkeypatch):
    instance = embedding_local.LocalQwenEmbedding.__new__(embedding_local.LocalQwenEmbedding)

    with pytest.raises(ValueError, match="文本Embedding必须使用GPU"):
        instance._resolve_device("cpu")

    monkeypatch.setattr(embedding_local.torch.cuda, "is_available", lambda: False)
    with pytest.raises(RuntimeError, match="当前CUDA不可用"):
        instance._resolve_device("cuda")


def test_local_embedding_oom_reduces_batch_without_cpu_fallback(monkeypatch):
    instance = embedding_local.LocalQwenEmbedding.__new__(embedding_local.LocalQwenEmbedding)
    instance.model_path = Path("/tmp/embedding-model")
    instance.device = "cuda"
    instance.sentence_model = object()
    instance.auto_model = None
    instance.batch_size = 8
    instance.dimension = 2
    instance._clear_cuda_cache = lambda: None
    calls: list[int] = []

    def fake_embed(_texts: list[str]) -> list[list[float]]:
        calls.append(instance.batch_size)
        if len(calls) == 1:
            raise RuntimeError("CUDA out of memory")
        return [[0.1, 0.2]]

    monkeypatch.setattr(instance, "_embed_with_sentence_transformer", fake_embed)

    assert instance.embed_texts(["text"]) == [[0.1, 0.2]]
    assert calls == [8, 4]
    assert instance.device == "cuda"

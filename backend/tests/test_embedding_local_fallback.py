import builtins
import sys
from pathlib import Path

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
    monkeypatch.setattr(embedding_local.LocalQwenEmbedding, "_load_transformers_model_with_fallback", fake_load_transformers)

    embedding_local.LocalQwenEmbedding(str(Path(".")), "cpu", 1, 1024)
    assert fallback_called["value"] is True

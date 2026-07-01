import sys
from pathlib import Path
from types import SimpleNamespace

BASE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE_DIR))

from app.retrieval.schemas import Evidence
from app.services import reranker_local
from app.services.reranker_service import RerankerService, RuntimeRerankerConfig


def _evidence() -> Evidence:
    return Evidence(
        score=0.61,
        source_type="project",
        knowledge_base_id=1,
        project_id=1,
        document_id=1,
        chunk_id=1,
        drawing_no="D-1",
        file_name="unit.md",
        page_number=1,
        content="真实 reranker 测试正文",
        retriever="milvus",
        metadata={"security_level": "public"},
    )


class _FakeLocalModel:
    def __init__(self, *, requested_device: str, resolved_device: str, batch_size: int = 8) -> None:
        self.requested_device = requested_device
        self.device = resolved_device
        self.batch_size = batch_size
        self.backend_name = "sentence-transformers-cross-encoder"
        self.is_loaded = True

    def predict(self, query: str, documents: list[str]) -> list[float]:  # noqa: ARG002
        return [0.87 for _ in documents]


def test_warmup_local_reranker_warns_when_device_not_explicitly_configured(monkeypatch) -> None:
    service = RerankerService(None)
    service.settings = SimpleNamespace(
        reranker_device="cpu",
        reranker_batch_size=8,
        model_fields_set=set(),
    )
    runtime_config = RuntimeRerankerConfig(provider="local", model_name="fake-model", api_base=None, api_key=None)
    warnings: list[str] = []

    monkeypatch.setattr(service, "_runtime_config", lambda config=None: runtime_config)
    monkeypatch.setattr(service, "_is_local_reranker", lambda config: True)
    monkeypatch.setattr(service, "_get_local_model", lambda config: _FakeLocalModel(requested_device="cpu", resolved_device="cpu"))
    monkeypatch.setattr("app.services.reranker_local.is_local_reranker_loaded", lambda *args, **kwargs: False)
    monkeypatch.setattr(
        "app.services.reranker_service.logger.warning",
        lambda message, *args, **kwargs: warnings.append(message % args if args else message),
    )

    service.warmup_local_reranker()

    assert warnings
    assert "RERANKER_DEVICE" in warnings[0]
    assert service.last_runtime["requested_device"] == "cpu"
    assert service.last_runtime["resolved_device"] == "cpu"
    assert service.last_runtime["device_explicitly_configured"] is False


def test_rerank_with_real_model_records_requested_and_resolved_device(monkeypatch) -> None:
    service = RerankerService(None)
    service.settings = SimpleNamespace(
        reranker_device="cuda",
        reranker_batch_size=4,
        model_fields_set={"reranker_device"},
    )
    runtime_config = RuntimeRerankerConfig(provider="local", model_name="fake-model", api_base=None, api_key=None)
    fake_model = _FakeLocalModel(requested_device="cuda", resolved_device="cuda", batch_size=4)

    monkeypatch.setattr(service, "_runtime_config", lambda config=None: runtime_config)
    monkeypatch.setattr(service, "_is_local_reranker", lambda config: True)
    monkeypatch.setattr(service, "_get_local_model", lambda config: fake_model)

    results = service.rerank("项目参数是什么", [_evidence()], limit=1, require_real_model=True, allow_fallback=False)

    assert results[0].metadata["rerank_requested_device"] == "cuda"
    assert results[0].metadata["rerank_resolved_device"] == "cuda"
    assert service.last_runtime["requested_device"] == "cuda"
    assert service.last_runtime["resolved_device"] == "cuda"
    assert service.last_runtime["device_explicitly_configured"] is True


def test_local_reranker_resolves_cuda_to_cpu_when_cuda_unavailable(monkeypatch) -> None:
    reranker = object.__new__(reranker_local.LocalCrossEncoderReranker)
    warnings: list[str] = []

    monkeypatch.setattr(reranker_local.torch.cuda, "is_available", lambda: False)
    monkeypatch.setattr(
        reranker_local.logger,
        "warning",
        lambda message, *args, **kwargs: warnings.append(message % args if args else message),
    )

    resolved_device = reranker._resolve_device("cuda")

    assert resolved_device == "cpu"
    assert warnings

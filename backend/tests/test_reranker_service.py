import sys
import threading
import time
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
        self._gate = threading.Lock()

    def predict(self, query: str, documents: list[str]) -> list[float]:  # noqa: ARG002
        return [0.87 for _ in documents]

    def acquire_inference_slot(self, timeout_seconds: float | None = None) -> int | None:
        started = time.perf_counter()
        if timeout_seconds is None:
            acquired = self._gate.acquire()
        else:
            acquired = self._gate.acquire(timeout=max(0.0, float(timeout_seconds)))
        wait_ms = int((time.perf_counter() - started) * 1000)
        if not acquired:
            return None
        return wait_ms

    def release_inference_slot(self) -> None:
        self._gate.release()


class _BlockingLocalModel(_FakeLocalModel):
    def __init__(self, *, requested_device: str, resolved_device: str, sleep_seconds: float) -> None:
        super().__init__(requested_device=requested_device, resolved_device=resolved_device)
        self.sleep_seconds = sleep_seconds
        self.predict_started = threading.Event()
        self.predict_finished = threading.Event()
        self.predict_calls = 0
        self.max_concurrent_predicts = 0
        self._predict_concurrency = 0
        self._counter_lock = threading.Lock()

    def predict(self, query: str, documents: list[str]) -> list[float]:  # noqa: ARG002
        with self._counter_lock:
            self.predict_calls += 1
            self._predict_concurrency += 1
            self.max_concurrent_predicts = max(self.max_concurrent_predicts, self._predict_concurrency)
        self.predict_started.set()
        try:
            time.sleep(self.sleep_seconds)
            return [0.91 for _ in documents]
        finally:
            with self._counter_lock:
                self._predict_concurrency -= 1
            self.predict_finished.set()


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
    assert service.last_runtime["queue_wait_ms"] >= 0
    assert service.last_runtime["prepare_elapsed_ms"] >= service.last_runtime["queue_wait_ms"]
    assert service.last_runtime["total_elapsed_ms"] >= service.last_runtime["elapsed_ms"]


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


def test_rerank_real_model_timeout_falls_back_to_deterministic(monkeypatch) -> None:
    service = RerankerService(None)
    service.settings = SimpleNamespace(reranker_timeout_seconds=0.05)

    monkeypatch.setattr(service, "_has_default_real_model", lambda: True)

    def slow_real_rerank(query: str, evidences: list[Evidence], limit: int, score_order: str) -> list[Evidence]:  # noqa: ARG001
        time.sleep(0.2)
        return evidences[:limit]

    monkeypatch.setattr(service, "_rerank_with_real_model", slow_real_rerank)

    started = time.perf_counter()
    results = service.rerank("项目参数是什么", [_evidence()], limit=1)
    elapsed = time.perf_counter() - started

    assert elapsed < 0.15
    assert results
    assert results[0].metadata["rerank_backend"] == "deterministic"
    assert service.last_runtime["fallback_used"] is True
    assert service.last_runtime["real_model_error"] == "real_reranker_timeout>0.05s"


def test_rerank_timeout_gate_prevents_parallel_real_model_predicts(monkeypatch) -> None:
    runtime_config = RuntimeRerankerConfig(provider="local", model_name="fake-model", api_base=None, api_key=None)
    fake_model = _BlockingLocalModel(requested_device="cuda", resolved_device="cuda", sleep_seconds=0.12)

    service_one = RerankerService(None)
    service_one.settings = SimpleNamespace(
        reranker_timeout_seconds=0.05,
        reranker_device="cuda",
        reranker_batch_size=8,
        model_fields_set={"reranker_device"},
    )
    service_two = RerankerService(None)
    service_two.settings = SimpleNamespace(
        reranker_timeout_seconds=0.05,
        reranker_device="cuda",
        reranker_batch_size=8,
        model_fields_set={"reranker_device"},
    )

    for service in (service_one, service_two):
        monkeypatch.setattr(service, "_has_default_real_model", lambda: True)
        monkeypatch.setattr(service, "_runtime_config", lambda config=None: runtime_config)
        monkeypatch.setattr(service, "_is_local_reranker", lambda config: True)
        monkeypatch.setattr(service, "_get_local_model", lambda config: fake_model)

    first_result: dict[str, object] = {}

    def run_first_request() -> None:
        reranked = service_one.rerank("Na2SO4蒸发流程", [_evidence()], limit=1)
        first_result["results"] = reranked
        first_result["runtime"] = dict(service_one.last_runtime)

    first_thread = threading.Thread(target=run_first_request, name="reranker-timeout-test")
    first_thread.start()

    assert fake_model.predict_started.wait(timeout=0.1) is True

    second_started = time.perf_counter()
    second_results = service_two.rerank("Na2SO4蒸发流程", [_evidence()], limit=1)
    second_elapsed = time.perf_counter() - second_started

    first_thread.join(timeout=1)
    assert first_thread.is_alive() is False
    assert fake_model.predict_finished.wait(timeout=0.3) is True

    first_runtime = first_result["runtime"]
    assert isinstance(first_runtime, dict)
    assert first_result["results"][0].metadata["rerank_backend"] == "deterministic"
    assert second_results[0].metadata["rerank_backend"] == "deterministic"
    assert second_elapsed < 0.12
    assert fake_model.predict_calls == 1
    assert fake_model.max_concurrent_predicts == 1
    assert first_runtime["real_model_runtime"]["timeout_stage"] == "inference"
    assert first_runtime["real_model_runtime"]["timed_out"] is True
    assert service_two.last_runtime["real_model_runtime"]["timeout_stage"] == "queue"
    assert service_two.last_runtime["real_model_runtime"]["queue_wait_ms"] >= 50

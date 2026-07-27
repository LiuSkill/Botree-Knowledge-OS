import json
import time
from types import SimpleNamespace

from app.services.multi_intent_models import IntentSubQuestion, QuestionIntent, QuestionIntentPlan
from app.services.multi_intent_qa_service import MultiIntentQaService
from app.services.qwen_orchestration_service import QwenOrchestrationService


def _intent(order: int, name: str, questions: list[str]) -> QuestionIntent:
    return QuestionIntent(
        id=f"intent-{order}",
        order=order,
        name=name,
        original_target=name,
        question="，".join(questions),
        sub_questions=[
            IntentSubQuestion(
                id=f"intent-{order}-sub-{sub_order}",
                order=sub_order,
                question=question,
                depends_on=[f"intent-{order}-sub-{sub_order - 1}"] if sub_order > 1 else [],
            )
            for sub_order, question in enumerate(questions, start=1)
        ],
    )


def _result(question: str) -> dict:
    return {
        "answer": f"回答：{question}",
        "answer_type": "normal_answer",
        "query_scope": "项目知识库",
        "used_retrievers": ["keyword"],
        "evidences": [],
        "agent_trace": [{"sequence": 1, "step": "检索", "implementation": "keyword", "status": "success"}],
        "raw": {
            "retrieval_plan": {"selected_retrievers": ["keyword"]},
            "evidence_evaluation": {"enough": True},
        },
    }


class _Graph:
    def __init__(self, *, delays=None, synthesis_error=False):
        self.delays = delays or {}
        self.synthesis_error = synthesis_error
        self.answer_generator = SimpleNamespace(synthesize_multi_intent=self._synthesize)

    def run_single_intent(self, question, *args, **kwargs):  # noqa: ARG002
        time.sleep(self.delays.get(question, 0))
        return _result(question)

    def _synthesize(self, question, answers):  # noqa: ARG002
        if self.synthesis_error:
            raise RuntimeError("synthesis unavailable")
        return "综合结论"

    @staticmethod
    def apply_final_answer_filter(state, answer):  # noqa: ARG004
        return None


def test_planner_omits_unrelated_overflow_and_preserves_structured_contract(monkeypatch):
    payload = {
        "intents": [
            {"id": "duplicate", "name": "设备", "original_target": "列出关键设备", "question": "列出关键设备", "sub_questions": ["列出关键设备"]},
            {"id": "duplicate", "name": "排放", "original_target": "核对排放限值", "question": "核对排放限值", "sub_questions": ["查找排放标准", {"question": "核对限值", "depends_on": ["1"]}]},
            {"id": "duplicate", "name": "排班", "original_target": "安排施工人员", "question": "安排施工人员", "sub_questions": ["安排施工人员"]},
            {"id": "duplicate", "name": "合同", "original_target": "评估合同法律风险", "question": "评估合同法律风险", "sub_questions": ["评估合同法律风险"]},
        ]
    }
    monkeypatch.setattr(
        "app.services.qwen_orchestration_service.LLMService",
        lambda db: SimpleNamespace(chat=lambda *args, **kwargs: json.dumps(payload, ensure_ascii=False)),
    )

    plan = QwenOrchestrationService(None).plan_question_intents(
        "分别列出设备、核对排放、安排人员，并评估合同风险，然后汇总",
        "project_chat",
        "auto",
    )

    assert [item.id for item in plan.intents] == ["intent-1", "intent-2", "intent-3"]
    assert [item.order for item in plan.intents] == [1, 2, 3]
    assert plan.intents[1].original_target == "核对排放限值"
    assert plan.intents[1].sub_questions[1].depends_on == ["1"]
    assert plan.omitted_targets == ["评估合同法律风险"]


def test_timeout_isolated_per_intent_and_answer_still_completes():
    plan = QuestionIntentPlan(intents=[_intent(1, "快速任务", ["快速问题"]), _intent(2, "慢任务", ["慢问题"])])
    service = MultiIntentQaService(_Graph(delays={"慢问题": 0.12}), None)
    service.settings = SimpleNamespace(multi_intent_timeout_seconds=0.05)

    events = list(service.execute_events("分别处理后汇总", plan, "project_chat", "auto", 1, SimpleNamespace(id=1)))
    result = next(payload for name, payload in events if name == "result")

    assert [item["status"] for item in result["intent_results"]] == ["success", "failed"]
    assert result["intent_results"][1]["failure_reason"] == "timeout"
    assert result["answer"].count("说明：") == 1
    assert "综合结论" in result["answer"]


def test_audit_attributes_plan_evaluation_and_trace_to_sub_question():
    plan = QuestionIntentPlan(
        intents=[_intent(1, "设备关系", ["列出设备", "说明上下游关系"]), _intent(2, "排放", ["核对排放"])]
    )
    result = MultiIntentQaService(_Graph(), None).execute(
        "分别回答并汇总", plan, "project_chat", "auto", 1, SimpleNamespace(id=1), business_id="session-1"
    )

    first_audit = result["intent_results"][0]["audit"]["sub_results"]
    assert first_audit[0]["retrieval_plan"] == {"selected_retrievers": ["keyword"]}
    assert first_audit[0]["evidence_evaluation"] == {"enough": True}
    assert first_audit[0]["failure_reason"] is None
    attributed_traces = [item for item in result["agent_trace"] if item.get("implementation") == "keyword"]
    assert {item["intent_id"] for item in attributed_traces} == {"intent-1", "intent-2"}
    assert all(item["sub_question_id"].startswith(item["intent_id"]) for item in attributed_traces)


def test_synthesis_failure_uses_safe_fallback_instead_of_failing_answer():
    plan = QuestionIntentPlan(intents=[_intent(1, "设备", ["列出设备"]), _intent(2, "流程", ["说明流程"])])
    result = MultiIntentQaService(_Graph(synthesis_error=True), None).execute(
        "分别回答并汇总", plan, "project_chat", "auto", 1, SimpleNamespace(id=1)
    )

    assert result["answer_type"] == "multi_intent_answer"
    assert "以上为各项任务基于当前可用资料得到的结果" in result["answer"]
    assert result["answer"].count("说明：") == 1

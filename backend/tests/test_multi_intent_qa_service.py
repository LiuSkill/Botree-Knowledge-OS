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
        "evidence_status": "ENOUGH",
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

    assert [item["status"] for item in result["intent_results"]] == ["completed", "timeout"]
    assert result["intent_results"][1]["failure_reason"] == "timeout"
    assert result["answer"].count("说明：") == 1
    assert "## 快速任务" in result["answer"]


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
    assert result["intent_results"][0]["sub_question_outcomes"][1]["depends_on"] == ["intent-1-sub-1"]
    attributed_traces = [item for item in result["agent_trace"] if item.get("implementation") == "keyword"]
    assert {item["intent_id"] for item in attributed_traces} == {"intent-1", "intent-2"}
    assert all(item["sub_question_id"].startswith(item["intent_id"]) for item in attributed_traces)
    assert all(item["parent_node_id"] == f"sub-question:{item['sub_question_id']}" for item in attributed_traces)
    assert {item["parallel_group_id"] for item in attributed_traces} == {f"turn:{result['raw']['turn_id']}:intents"}


def test_synthesis_failure_uses_safe_fallback_instead_of_failing_answer():
    plan = QuestionIntentPlan(intents=[_intent(1, "设备", ["列出设备"]), _intent(2, "流程", ["说明流程"])])
    result = MultiIntentQaService(_Graph(synthesis_error=True), None).execute(
        "分别回答并汇总", plan, "project_chat", "auto", 1, SimpleNamespace(id=1)
    )

    assert result["answer_type"] == "multi_intent_answer"
    assert "## 设备" in result["answer"]
    assert "## 流程" in result["answer"]
    assert "综合结论" not in result["answer"]


def test_intent_outcomes_are_structured_and_final_answer_has_no_duplicate_markdown() -> None:
    plan = QuestionIntentPlan(intents=[_intent(1, "装机功率统计", ["列出装机功率", "汇总装机功率"])])
    result = MultiIntentQaService(_Graph(), None).execute(
        "本项目的总装机功率是多少？分别列出然后汇总",
        plan,
        "project_chat",
        "auto",
        1,
        SimpleNamespace(id=1),
        business_id="session-9",
    )

    assert result["intent_results"][0]["status"] == "completed"
    assert result["intent_results"][0]["answerability_status"] == "answered"
    assert result["intent_results"][0]["sub_question_outcomes"][0]["answerability_status"] == "answered"
    assert result["raw"]["planned_intent_ids"] == ["intent-1"]
    assert result["raw"]["executed_intent_ids"] == ["intent-1"]
    assert result["raw"]["answered_intent_ids"] == ["intent-1"]
    assert "###" not in result["answer"]
    assert "小结" not in result["answer"]
    assert "完成 2/2 个子问题" not in result["answer"]


def test_insufficient_evidence_is_reported_separately_from_execution_completion() -> None:
    class InsufficientGraph(_Graph):
        def run_single_intent(self, question, *args, **kwargs):  # noqa: ARG002
            result = _result(question)
            result["answer"] = "资料不足，未获得明确答案。"
            result["answer_type"] = "refusal"
            result["evidence_status"] = "EMPTY"
            result["raw"]["evidence_evaluation"] = {"enough": False, "missing_aspects": ["总装机功率台账"]}
            return result

    plan = QuestionIntentPlan(intents=[_intent(1, "装机功率统计", ["列出装机功率"])])
    result = MultiIntentQaService(InsufficientGraph(), None).execute(
        "本项目的总装机功率是多少？",
        plan,
        "project_chat",
        "auto",
        1,
        SimpleNamespace(id=1),
    )

    outcome = result["intent_results"][0]
    assert outcome["status"] == "completed"
    assert outcome["answerability_status"] == "insufficient_evidence"
    assert outcome["missing_information"] == ["总装机功率台账"]
    assert "资料不足，未获得明确答案" in result["answer"]


def test_partial_single_intent_answer_deduplicates_repeated_conflict_copy() -> None:
    repeated_answer = (
        "检索到的资料之间存在冲突，当前无法基于知识库给出确定结论。\n"
        "问题：本项目的总装机功率是多少？分别列出然后汇总\n"
        "冲突证据编号：1, 3\n"
        "建议优先核对资料版本、审核状态、来源优先级和发布日期后再确认。"
    )

    class PartialGraph(_Graph):
        def run_single_intent(self, question, *args, **kwargs):  # noqa: ARG002
            result = _result(question)
            result["answer"] = repeated_answer
            result["answer_type"] = "conflict_answer"
            result["evidence_status"] = "CONFLICTED"
            if "列出" in question:
                result["raw"]["evidence_evaluation"] = {
                    "reason": "召回证据中存在数值冲突，且缺乏完整分项列表。",
                    "missing_aspects": [
                        "明确的'本项目总装机功率'定义性陈述",
                        "完整的设备功率分项列表以支持'分别列出'",
                        "对证据间数值冲突（118 KW vs 731.25 KW）的上下文解释",
                        "确认 731.25 KW 是否为最终项目总和而非局部汇总",
                    ],
                }
            else:
                result["raw"]["evidence_evaluation"] = {
                    "reason": "召回证据中存在数值冲突，且缺乏明确的项目级总述段落。",
                    "missing_aspects": [
                        "明确的'本项目总装机功率'定义语句",
                        "所有分项设备的完整列表以支持'分别列出'",
                        "对证据间数值冲突（118 KW vs 731.25 KW）的上下文解释",
                        "确认 731.25 KW 是否为最终项目总和而非局部汇总",
                    ],
                }
            return result

    plan = QuestionIntentPlan(intents=[_intent(1, "装机功率统计", ["列出装机功率", "汇总装机功率"])])
    result = MultiIntentQaService(PartialGraph(), None).execute(
        "本项目的总装机功率是多少？分别列出然后汇总",
        plan,
        "project_chat",
        "auto",
        1,
        SimpleNamespace(id=1),
    )

    outcome = result["intent_results"][0]
    assert outcome["answerability_status"] == "partially_answered"
    assert outcome["conclusion"].count("检索到的资料之间存在冲突") == 1
    assert result["answer"].count("检索到的资料之间存在冲突") == 1
    assert len(outcome["missing_information"]) == 4
    assert ("定义性陈述" in result["answer"]) ^ ("定义语句" in result["answer"])
    assert ("完整的设备功率分项列表" in result["answer"]) ^ ("所有分项设备的完整列表" in result["answer"])

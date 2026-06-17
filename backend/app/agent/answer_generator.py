"""Answer Generator

负责：
1. 基于检索证据调用真实 LLM 生成回答
2. 无证据时明确提示无法回答
3. 统一同步与流式问答入口
"""

from collections.abc import Iterator

from sqlalchemy.orm import Session

from app.retrieval.schemas import Evidence
from app.services.llm_service import LLMService


class AnswerGenerator:
    """回答生成器。"""

    def __init__(self, db: Session) -> None:
        self.llm_service = LLMService(db)

    def generate(self, question: str, evidences: list[Evidence]) -> str:
        """生成完整回答。"""

        if any(evidence.assets for evidence in evidences):
            return self.llm_service.answer_with_multimodal_evidence(question, evidences)
        return self.llm_service.answer_with_evidence(question, evidences)

    def stream_generate(self, question: str, evidences: list[Evidence]) -> Iterator[str]:
        """流式生成回答。"""

        if any(evidence.assets for evidence in evidences):
            yield from self.llm_service.stream_answer_with_multimodal_evidence(question, evidences)
            return
        yield from self.llm_service.stream_answer_with_evidence(question, evidences)

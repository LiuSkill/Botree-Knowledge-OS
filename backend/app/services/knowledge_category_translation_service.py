"""Knowledge category translation service."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.services.llm_service import LLMService

logger = logging.getLogger(__name__)

_CJK_PATTERN = re.compile(r"[\u3400-\u9fff]")
_JSON_OBJECT_PATTERN = re.compile(r"\{.*\}", re.S)
_LANGUAGE_NEUTRAL_PATTERN = re.compile(r"^[A-Z0-9][A-Z0-9&./+\-_\s]*$")
_MAX_CATEGORY_NAME_LENGTH = 100


@dataclass(frozen=True)
class TranslatedCategoryNames:
    """分类双语名称。"""

    name_zh: str
    name_en: str


class KnowledgeCategoryTranslationService:
    """自动补齐知识分类的中英文名称。"""

    def __init__(self, db: Session) -> None:
        self.db = db

    def complete_names(
        self,
        source_name: str,
        *,
        name_zh: str | None = None,
        name_en: str | None = None,
    ) -> TranslatedCategoryNames:
        """按用户输入语言补齐另一个语种，模型不可用时回退原名。"""

        source = self._clean_name(source_name)
        if not source:
            return TranslatedCategoryNames(name_zh="", name_en="")

        resolved_zh = self._valid_chinese_name(source, name_zh)
        resolved_en = self._valid_english_name(name_en)
        if not resolved_zh and not resolved_en:
            if self._looks_chinese(source):
                resolved_zh = source
                resolved_en = self._translate(source, source_language="zh-CN", target_language="en-US") or source
            else:
                resolved_en = source
                resolved_zh = self._translate(source, source_language="en-US", target_language="zh-CN") or source
        elif resolved_zh and not resolved_en:
            resolved_en = self._translate(resolved_zh, source_language="zh-CN", target_language="en-US") or resolved_zh
        elif resolved_en and not resolved_zh:
            resolved_zh = self._translate(resolved_en, source_language="en-US", target_language="zh-CN") or resolved_en

        return TranslatedCategoryNames(
            name_zh=self._clamp_name(resolved_zh or source),
            name_en=self._clamp_name(resolved_en or source),
        )

    def needs_repair(self, source_name: str, *, name_zh: str | None = None, name_en: str | None = None) -> bool:
        """判断双语名称是否缺失或仍停留在错误语种。"""

        source = self._clean_name(source_name)
        if not source:
            return False
        return not self._valid_chinese_name(source, name_zh) or not self._valid_english_name(name_en)

    def _translate(self, text: str, *, source_language: str, target_language: str) -> str | None:
        """调用 LLM 翻译短分类名；失败只影响译文字段，不阻断主业务。"""

        try:
            raw_result = LLMService(self.db).chat(
                [
                    {
                        "role": "system",
                        "content": (
                            "You translate short knowledge-base category names for battery recycling, "
                            "hydrometallurgy, engineering design, project document management, and EHS. "
                            "Return strict JSON only: {\"translation\":\"...\"}. "
                            "Keep acronyms such as WBS, PFD, P&ID, EHS, PDF, CAD unchanged."
                        ),
                    },
                    {
                        "role": "user",
                        "content": json.dumps(
                            {
                                "source_language": source_language,
                                "target_language": target_language,
                                "text": text,
                                "style": "concise category label",
                            },
                            ensure_ascii=False,
                        ),
                    },
                ],
                model_type="analysis_llm",
                timeout_seconds=15,
                max_tokens=160,
                disable_thinking=True,
            )
            return self._parse_translation(raw_result)
        except Exception as exc:  # noqa: BLE001 - 翻译失败不应阻断分类维护主流程。
            logger.warning(
                "知识分类自动翻译失败，使用原名兜底: source_language=%s target_language=%s error=%s",
                source_language,
                target_language,
                exc,
            )
            return None

    def _parse_translation(self, raw_result: str) -> str | None:
        """解析模型返回的 JSON 翻译结果。"""

        raw_text = str(raw_result or "").strip()
        if not raw_text:
            return None
        try:
            payload = json.loads(raw_text)
        except json.JSONDecodeError:
            match = _JSON_OBJECT_PATTERN.search(raw_text)
            if not match:
                logger.warning("知识分类自动翻译返回非JSON内容，已忽略: raw=%s", raw_text[:200])
                return None
            try:
                payload = json.loads(match.group(0))
            except json.JSONDecodeError:
                logger.warning("知识分类自动翻译JSON解析失败，已忽略: raw=%s", raw_text[:200])
                return None
        translation = payload.get("translation") if isinstance(payload, dict) else None
        return self._clean_name(str(translation)) if translation else None

    @staticmethod
    def _looks_chinese(text: str) -> bool:
        return bool(_CJK_PATTERN.search(text))

    @classmethod
    def _is_language_neutral(cls, text: str) -> bool:
        return bool(_LANGUAGE_NEUTRAL_PATTERN.fullmatch(cls._clean_name(text)))

    @classmethod
    def _valid_chinese_name(cls, source_name: str, value: str | None) -> str:
        cleaned = cls._clean_name(value)
        if not cleaned:
            return ""
        if cls._looks_chinese(cleaned) or cls._is_language_neutral(cleaned):
            return cleaned
        return ""

    @classmethod
    def _valid_english_name(cls, value: str | None) -> str:
        cleaned = cls._clean_name(value)
        if not cleaned or cls._looks_chinese(cleaned):
            return ""
        return cleaned

    @staticmethod
    def _clean_name(value: str | None) -> str:
        return re.sub(r"\s+", " ", str(value or "").strip().strip('"“”'))[:_MAX_CATEGORY_NAME_LENGTH]

    @staticmethod
    def _clamp_name(value: str) -> str:
        return value[:_MAX_CATEGORY_NAME_LENGTH]

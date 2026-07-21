"""运行时敏感内容过滤及配置服务。"""

from __future__ import annotations

from dataclasses import dataclass
import json
import logging
import re
import threading
import time

from sqlalchemy.orm import Session

from app.core.exceptions import AppException
from app.core.rbac import is_admin
from app.models.sensitive_content import SensitiveFilterRule, SensitiveType
from app.models.user import User
from app.models.user import Role
from app.repositories.sensitive_content_repository import SensitiveContentRepository
from app.services.table_sensitive_filter import TABLE_MATCH_TYPES, TableSensitiveFilter

logger = logging.getLogger(__name__)
SECURITY_NOTICE = "部分敏感信息因权限限制未展示。"


@dataclass(frozen=True)
class CompiledRule:
    code: str
    sensitive_type_code: str
    match_type: str
    regex: re.Pattern[str]
    context_keywords: tuple[str, ...]
    window_size: int
    mask_text: str
    priority: int


@dataclass(frozen=True)
class FilterResult:
    safe_content: str
    redacted: bool
    redaction_types: tuple[str, ...]
    redaction_count: int
    matched_rule_codes: tuple[str, ...] = ()


class SensitiveRuntimeFilter:
    """先执行表格结构过滤，再以文本规则兜底。"""

    def __init__(self) -> None:
        self.table_filter = TableSensitiveFilter()

    def filter(self, content: str, allowed_types: set[str], rules: tuple[CompiledRule, ...]) -> FilterResult:
        if not content:
            return FilterResult(content, False, (), 0)
        table_result = self.table_filter.filter(content, allowed_types, rules)
        text_result = self._filter_text(
            table_result.safe_content,
            allowed_types,
            tuple(rule for rule in rules if rule.match_type not in TABLE_MATCH_TYPES),
        )
        redaction_types = tuple(sorted(set(table_result.redaction_types) | set(text_result.redaction_types)))
        matched_codes = tuple(sorted(set(table_result.matched_rule_codes) | set(text_result.matched_rule_codes)))
        redaction_count = table_result.redaction_count + text_result.redaction_count
        return FilterResult(text_result.safe_content, redaction_count > 0, redaction_types, redaction_count, matched_codes)

    @staticmethod
    def _filter_text(content: str, allowed_types: set[str], rules: tuple[CompiledRule, ...]) -> FilterResult:
        matches: list[tuple[int, int, str, str, int, int, str]] = []
        for rule in rules:
            if rule.sensitive_type_code in allowed_types:
                continue
            for match in rule.regex.finditer(content):
                if rule.match_type == "keyword_window":
                    start = max(0, match.start() - rule.window_size)
                    end = min(len(content), match.end() + rule.window_size)
                    context = content[start:end]
                    keyword_positions = [(context.find(keyword), len(keyword)) for keyword in rule.context_keywords if keyword and keyword in context]
                    if not keyword_positions:
                        continue
                    local_match_start = match.start() - start
                    # 金额通常位于关键词之后；按关键词末端距离可让“供应商报价”优先于其子串“报价”。
                    keyword_distance = min(abs(position + length - local_match_start) for position, length in keyword_positions)
                else:
                    keyword_distance = 0
                matches.append((match.start(), match.end(), rule.sensitive_type_code, rule.mask_text, rule.priority, keyword_distance, rule.code))
        if not matches:
            return FilterResult(content, False, (), 0)
        # 优先级更高的规则先占用区间，避免合同价同时按报价和合同金额重复替换。
        selected: list[tuple[int, int, str, str, int, int, str]] = []
        for candidate in sorted(matches, key=lambda item: (item[5], item[4], item[0], -(item[1] - item[0]))):
            if any(candidate[0] < item[1] and item[0] < candidate[1] for item in selected):
                continue
            selected.append(candidate)
        safe_content = content
        for start, end, _, mask_text, _, _, _ in sorted(selected, key=lambda item: item[0], reverse=True):
            safe_content = safe_content[:start] + mask_text + safe_content[end:]
        types = tuple(sorted({item[2] for item in selected}))
        rule_codes = tuple(sorted({item[6] for item in selected}))
        return FilterResult(safe_content, True, types, len(selected), rule_codes)


class SensitiveRuleService:
    _lock = threading.Lock()
    _expires_at = 0.0
    _cache: tuple[dict[str, SensitiveType], tuple[CompiledRule, ...]] | None = None

    def __init__(self, db: Session, ttl_seconds: int = 60) -> None:
        self.repository = SensitiveContentRepository(db)
        self.ttl_seconds = ttl_seconds

    def load(self) -> tuple[dict[str, SensitiveType], tuple[CompiledRule, ...]]:
        now = time.monotonic()
        if self.__class__._cache is not None and now < self.__class__._expires_at:
            return self.__class__._cache
        with self.__class__._lock:
            if self.__class__._cache is not None and now < self.__class__._expires_at:
                return self.__class__._cache
            types = {item.code: item for item in self.repository.list_types(enabled_only=True)}
            compiled: list[CompiledRule] = []
            for rule in self.repository.list_rules(enabled_only=True):
                sensitive_type = types.get(rule.sensitive_type_code)
                if sensitive_type is None:
                    continue
                try:
                    keywords = tuple(json.loads(rule.context_keywords or "[]"))
                    compiled.append(CompiledRule(rule.code, rule.sensitive_type_code, rule.match_type, re.compile(rule.pattern), keywords, rule.window_size, rule.mask_text or sensitive_type.default_mask_text, rule.priority))
                except (re.error, TypeError, ValueError, json.JSONDecodeError) as exc:
                    logger.error("敏感规则编译失败: rule_id=%s code=%s error=%s", rule.id, rule.code, exc)
            self.__class__._cache = (types, tuple(compiled))
            self.__class__._expires_at = now + self.ttl_seconds
            return self.__class__._cache

    @classmethod
    def refresh(cls) -> None:
        with cls._lock:
            cls._cache = None
            cls._expires_at = 0.0


class RoleSensitivePermissionService:
    def __init__(self, db: Session) -> None:
        self.repository = SensitiveContentRepository(db)
        self.rule_service = SensitiveRuleService(db)

    def allowed_types(self, user: User) -> set[str]:
        enabled_types = set(self.rule_service.load()[0])
        if is_admin(user):
            return enabled_types
        role_ids = {role.id for role in user.roles if role.enabled}
        return self.repository.allowed_types(role_ids) & enabled_types


class SensitiveContentService:
    def __init__(self, db: Session | None) -> None:
        self.db = db
        self.rule_service = SensitiveRuleService(db) if db is not None else None
        self.permission_service = RoleSensitivePermissionService(db) if db is not None else None
        self.runtime_filter = SensitiveRuntimeFilter()

    def filter_for_user(self, content: str, user: User) -> FilterResult:
        allowed_types, rules = self.runtime_config_for_user(user)
        return self.runtime_filter.filter(content, allowed_types, rules)

    def runtime_config_for_user(self, user: User) -> tuple[set[str], tuple[CompiledRule, ...]]:
        """一次请求只加载一次规则和角色授权，供多个证据片段复用。"""

        if self.rule_service is None or self.permission_service is None:
            return set(), _fallback_rules()
        _, rules = self.rule_service.load()
        return self.permission_service.allowed_types(user), rules

    @staticmethod
    def validate_rule(rule: SensitiveFilterRule) -> None:
        if rule.match_type not in {"regex", "keyword", "keyword_window", "table_column", "table_row", "table_cell"}:
            raise AppException("不支持的敏感规则匹配方式", status_code=422, code=422)
        try:
            re.compile(rule.pattern)
            keywords = json.loads(rule.context_keywords or "[]")
            if not isinstance(keywords, list):
                raise ValueError("context_keywords 必须是数组")
        except (re.error, ValueError, TypeError, json.JSONDecodeError) as exc:
            raise AppException(f"敏感规则配置无效: {exc}", status_code=422, code=422) from exc


class SensitiveContentManagementService:
    """管理敏感配置并在写入成功后使运行时缓存立即失效。"""

    def __init__(self, db: Session) -> None:
        self.db = db
        self.repository = SensitiveContentRepository(db)

    def save_type(self, payload: dict, item_id: int | None = None) -> SensitiveType:
        item = self.repository.get_type(item_id) if item_id else SensitiveType()
        if item is None:
            raise AppException("敏感类型不存在", status_code=404, code=404)
        for key, value in payload.items():
            setattr(item, key, value)
        self.repository.add(item)
        self.db.commit()
        SensitiveRuleService.refresh()
        return item

    def save_rule(self, payload: dict, item_id: int | None = None) -> SensitiveFilterRule:
        item = self.repository.get_rule(item_id) if item_id else SensitiveFilterRule(version=1)
        if item is None:
            raise AppException("敏感规则不存在", status_code=404, code=404)
        values = dict(payload)
        values["context_keywords"] = json.dumps(values.get("context_keywords", []), ensure_ascii=False)
        for key, value in values.items():
            setattr(item, key, value)
        if item_id:
            item.version += 1
        SensitiveContentService.validate_rule(item)
        self.repository.add(item)
        self.db.commit()
        SensitiveRuleService.refresh()
        return item

    def save_role_permissions(self, role_id: int, values: dict[str, bool]) -> None:
        if self.db.get(Role, role_id) is None:
            raise AppException("角色不存在", status_code=404, code=404)
        valid_codes = {item.code for item in self.repository.list_types()}
        if set(values) - valid_codes:
            raise AppException("包含不存在的敏感类型", status_code=422, code=422)
        self.repository.replace_role_permissions(role_id, values)
        self.db.commit()

    @staticmethod
    def rule_dict(item: SensitiveFilterRule) -> dict:
        return {
            "id": item.id, "code": item.code, "name": item.name, "sensitive_type_code": item.sensitive_type_code,
            "match_type": item.match_type, "pattern": item.pattern, "context_keywords": json.loads(item.context_keywords or "[]"),
            "window_size": item.window_size, "mask_text": item.mask_text, "priority": item.priority, "enabled": item.enabled,
            "version": item.version, "created_at": item.created_at, "updated_at": item.updated_at,
        }


def _fallback_rules() -> tuple[CompiledRule, ...]:
    """数据库会话不可用时采用保守内置规则，避免测试/降级链路默认放行。"""

    amount = re.compile(r"(?:(?:USD|CNY|RMB|￥|¥|\$)\s*\d+(?:\.\d+)?(?:\s*(?:万|亿|千)?\s*(?:元|人民币|美元|美金))?|\d+(?:\.\d+)?\s*(?:万|亿|千)?\s*(?:元|人民币|美元|美金))(?:\s*/\s*[\u4e00-\u9fa5A-Za-z]+)?")
    return (
        CompiledRule("table_supplier_price_column_rule", "supplier_price", "table_column", re.compile(r"供应商报价|采购报价|供应商价格|供应商单价|供货价"), (), 30, "[供应商报价已隐藏]", 5),
        CompiledRule("table_price_column_rule", "price", "table_column", re.compile(r"报价|价格|单价|销售单价|总价|投标价|中标价|供货价"), (), 30, "[报价信息已隐藏]", 10),
        CompiledRule("table_cost_column_rule", "cost", "table_column", re.compile(r"成本|采购成本|设备成本|制造成本|建设成本|成本价|采购价"), (), 30, "[成本信息已隐藏]", 20),
        CompiledRule("table_margin_column_rule", "gross_margin", "table_column", re.compile(r"毛利率|利润率|毛利|利润空间"), (), 30, "[利润率信息已隐藏]", 30),
        CompiledRule("table_contract_amount_column_rule", "contract_amount", "table_column", re.compile(r"合同金额|合同总价|合同价|订单金额|订单总价"), (), 30, "[合同金额已隐藏]", 40),
        CompiledRule("table_payment_terms_column_rule", "payment_terms", "table_column", re.compile(r"付款条件|付款方式|预付款|尾款|账期|验收后支付"), (), 30, "[付款条件已隐藏]", 50),
        CompiledRule("supplier_price_rule", "supplier_price", "keyword_window", amount, ("供应商报价", "采购报价", "报价单", "供应商价格"), 30, "[供应商报价已隐藏]", 5),
        CompiledRule("price_amount_rule", "price", "keyword_window", amount, ("报价", "价格", "销售价", "销售单价", "合同价", "总价", "投标价", "中标价", "商务报价", "供货价"), 30, "[报价信息已隐藏]", 10),
        CompiledRule("cost_amount_rule", "cost", "keyword_window", amount, ("成本", "采购成本", "设备成本", "制造成本", "建设成本", "成本价", "采购价"), 30, "[成本信息已隐藏]", 20),
        CompiledRule("gross_margin_rule", "gross_margin", "keyword_window", re.compile(r"\d+(?:\.\d+)?\s*%"), ("毛利率", "利润率", "毛利", "利润空间"), 30, "[利润率信息已隐藏]", 30),
        CompiledRule("contract_amount_rule", "contract_amount", "keyword_window", amount, ("合同金额", "合同总价", "合同价", "订单金额", "订单总价"), 30, "[合同金额已隐藏]", 40),
        CompiledRule("payment_terms_rule", "payment_terms", "keyword", re.compile(r"预付款|尾款|账期|付款条件|付款方式|验收后支付|合同款"), (), 30, "[付款条件已隐藏]", 50),
        CompiledRule("business_strategy_rule", "business_strategy", "keyword", re.compile(r"让利空间|价格底线|谈判空间|商务条件|底价"), (), 30, "[商务策略信息已隐藏]", 60),
        CompiledRule("financial_metric_rule", "financial_metric", "keyword", re.compile(r"\bIRR\b|\bNPV\b|投资回收期|现金流|财务回报率"), (), 30, "[财务指标已隐藏]", 70),
    )

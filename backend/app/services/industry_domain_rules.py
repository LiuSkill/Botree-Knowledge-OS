"""Industry domain rule helpers.

集中维护行业基础知识识别规则，供意图路由和 Query Profile 复用。
"""

from __future__ import annotations

from app.retrieval.query_utils import normalize_query_text

INDUSTRY_DOMAIN_KEYWORDS: dict[str, tuple[str, ...]] = {
    "battery_recycling": (
        "黑粉",
        "black mass",
        "电池回收",
        "动力电池回收",
        "电池黑粉",
        "lfp",
        "ncm",
        "磷酸铁锂",
        "三元材料",
        "正极材料",
        "ni/co/mn/li",
    ),
    "hydrometallurgy": (
        "湿法冶金",
        "酸浸",
        "浸出",
        "萃取",
        "反萃",
        "沉淀法",
        "提锂",
        "除铝",
        "沉淀",
        "ph",
        "化学工艺",
    ),
    "process_design": (
        "工艺包",
        "工艺设计",
        "工艺开发",
        "工艺路线",
        "设备位号",
        "管道仪表图",
        "阀门符号",
        "图纸识读",
    ),
    "pid_pfd": (
        "pfd",
        "p&id",
        "pid",
        "p＆id",
        "管道仪表图",
        "工艺流程图",
    ),
    "equipment": (
        "离心机",
        "压滤机",
        "过滤器",
        "mvr",
        "搅拌釜",
        "设备选型",
        "公辅",
        "干燥包装",
        "石墨",
    ),
    "safety_environment": (
        "安全环保",
        "废气处理",
        "废气",
        "废水",
        "尾气",
        "环保法规",
    ),
}


def detect_industry_domains(question: str) -> list[str]:
    """
    识别问题命中的行业基础知识领域。

    参数:
        question: 用户原始问题。

    返回:
        去重后的行业领域编码列表。
    """

    normalized = normalize_query_text(question)
    lowered = normalized.lower()
    domains: list[str] = []
    for domain, keywords in INDUSTRY_DOMAIN_KEYWORDS.items():
        if any(keyword.lower() in lowered for keyword in keywords):
            domains.append(domain)
    return domains


def is_industry_domain_question(question: str) -> bool:
    """判断问题是否属于电池回收、湿法冶金、工艺设计等行业基础知识。"""

    return bool(detect_industry_domains(question))

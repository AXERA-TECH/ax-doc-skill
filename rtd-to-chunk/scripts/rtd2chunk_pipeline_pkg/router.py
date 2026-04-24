"""Document classification: RTD文档的启发式分类逻辑"""

from __future__ import annotations

import logging

from .models import DocumentClassification, DocumentType

logger = logging.getLogger(__name__)


def rule_based_classify(title: str, content: str) -> DocumentClassification:
    normalized_content = content
    title_lower = title.lower()
    content_lower = normalized_content.lower()
    merged = f"{title_lower}\n{content_lower}"

    overview_title_signals = [s for s in ("概述", "简介", "introduction", "overview") if s in title_lower]
    if overview_title_signals and "quick start" not in title_lower and "快速开始" not in title:
        return DocumentClassification(DocumentType.OVERVIEW, 0.84, "规则命中 overview 标题信号。", overview_title_signals)

    quick_start_signals = [
        s for s in ("快速开始", "quick start", "开发环境准备", "环境准备", "前置条件", "步骤", "安装", "运行示例")
        if s in title_lower or s in content_lower
    ]
    strong_quick_start_title = any(s in title_lower for s in ("quick start", "快速开始"))
    if any(signal in title for signal in ("开发环境准备", "环境准备")) and "配置文件" not in title:
        strong_quick_start_title = True
    if quick_start_signals and strong_quick_start_title:
        return DocumentClassification(DocumentType.QUICK_START, 0.8, "规则命中 quick_start 标题信号。", quick_start_signals)

    strong_parameter_title_signals = [s for s in ("参数", "参数说明", "参数参考", "配置文件", "配置参考", "reference", "config") if s in title_lower]
    strong_parameter_content_signals = [s for s in ("默认值", "取值范围", "required", "default", "option:", "字段", "属性") if s in content_lower]
    weak_parameter_content_signals = [s for s in ("参数", "配置", "attribute", "parameter") if s in content_lower]
    if strong_parameter_title_signals or (len(strong_parameter_content_signals) >= 2 and len(weak_parameter_content_signals) >= 1):
        matched = list(dict.fromkeys(strong_parameter_title_signals + strong_parameter_content_signals + weak_parameter_content_signals))
        return DocumentClassification(DocumentType.PARAMETER_REFERENCE, 0.74, "规则命中参数参考信号。", matched)

    strong_list_title_signals = [
        s for s in ("支持列表", "算子支持列表", "support list", "op_support_list", "faq", "索引", "资源列表", "能力列表", "清单")
        if s in title_lower
    ]
    strong_list_content_signals = [s for s in ("支持列表", "算子支持列表", "support list", "op_support_list", "常见问题", "faq", "资源列表") if s in merged]
    weak_list_signals = [s for s in ("列表", "清单", "索引") if s in title or s in normalized_content]
    if strong_list_title_signals or (strong_list_content_signals and len(weak_list_signals) >= 2):
        matched = list(dict.fromkeys(strong_list_title_signals + strong_list_content_signals))
        return DocumentClassification(DocumentType.LIST, 0.76, "规则命中列表类信号。", matched)

    return DocumentClassification(DocumentType.OVERVIEW, 0.55, "未命中强信号，默认 overview。", ["default_overview"])



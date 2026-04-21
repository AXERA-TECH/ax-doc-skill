"""Document classification: rule-based and optional LLM router."""

from __future__ import annotations

import json
import logging
import os

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


def _normalize_document_type(value: str) -> DocumentType:
    normalized = value.strip().lower()
    alias_map: dict[str, DocumentType] = {}
    for item in DocumentType:
        for alias in item.router_aliases:
            alias_map[alias.lower()] = item
    if normalized not in alias_map:
        raise ValueError(f"Unsupported document_type from LLM: {value}")
    return alias_map[normalized]


def _build_router_prompt() -> str:
    type_priority_rules: dict[DocumentType, str] = {
        DocumentType.QUICK_START: "若文档既有概述也有步骤，但核心目的是带用户快速完成一次操作，优先判定为 quick_start。",
        DocumentType.PARAMETER_REFERENCE: "若文档主要在解释参数、字段或配置项，即使有少量示例，也优先判定为 parameter_reference。",
        DocumentType.LIST: "若文档主要由条目枚举构成，而不是完整讲解或操作流程，优先判定为 list。",
        DocumentType.OVERVIEW: "若文档是高层介绍、设计理念、背景说明或能力总览，优先判定为 overview。",
    }
    type_lines: list[str] = []
    for idx, item in enumerate(DocumentType, start=1):
        aliases = "/".join(item.router_aliases)
        type_lines.append(
            f"{idx}. {item.value}（别名: {aliases}）：{item.classification_description}"
            f" 分类优先规则：{type_priority_rules[item]}"
        )
    allowed = "|".join(item.value for item in DocumentType)

    return (
        "你是一个文档路由分类器。"
        "你的任务是根据文档标题和正文内容，将文档严格分类到以下类型之一：\n"
        + "\n".join(type_lines)
        + "\n\n通用约束：必须且只能选择一个最主要的文档类型。\n\n"
        "Return strict JSON only: "
        f'{{"document_type":"{allowed}","confidence":0.0,"reasoning":"...","matched_signals":["..."]}}.'
    )


async def llm_classify(
    title: str,
    content: str,
    *,
    model: str | None = None,
    api_key: str | None = None,
    base_url: str | None = None,
    timeout_seconds: int = 20,
) -> DocumentClassification:
    key = api_key or os.getenv("OPENAI_API_KEY")
    if not key:
        raise ValueError("OPENAI_API_KEY is required for llm router mode")
    endpoint = (base_url or os.getenv("OPENAI_BASE_URL") or "https://api.openai.com/v1").rstrip("/")
    model_name = model or os.getenv("OPENAI_MODEL") or "gpt-4o-mini"

    truncated = content[:6000]
    prompt = _build_router_prompt()
    user_input = f"title:\n{title}\n\ncontent:\n{truncated}"
    body = {
        "model": model_name,
        "temperature": 0,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": prompt},
            {"role": "user", "content": user_input},
        ],
    }
    try:
        from openai import AsyncOpenAI  # type: ignore
    except ImportError as exc:
        raise RuntimeError("openai package is required for llm router mode") from exc

    client = AsyncOpenAI(
        api_key=key,
        base_url=endpoint,
        timeout=float(timeout_seconds),
    )
    try:
        response = await client.chat.completions.create(
            model=body["model"],
            temperature=body["temperature"],
            response_format=body["response_format"],
            messages=body["messages"],
        )
    except Exception as exc:
        raise RuntimeError(f"LLM classify request failed: {exc}") from exc

    content_text = response.choices[0].message.content or ""
    result = json.loads(content_text)

    doc_type = _normalize_document_type(str(result.get("document_type", "")))
    confidence = float(result.get("confidence", 0.65))
    confidence = max(0.0, min(1.0, confidence))
    reasoning = str(result.get("reasoning", "LLM classification"))
    signals = result.get("matched_signals")
    if not isinstance(signals, list):
        signals = ["llm_router"]
    signals = [str(item) for item in signals if str(item).strip()]
    if not signals:
        signals = ["llm_router"]
    return DocumentClassification(
        document_type=doc_type,
        confidence=confidence,
        reasoning=reasoning,
        matched_signals=signals,
    )

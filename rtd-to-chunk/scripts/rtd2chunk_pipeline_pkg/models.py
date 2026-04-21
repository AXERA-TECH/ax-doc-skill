"""
Flow
----
dataclass/enums
  -> RawDocument / DocumentClassification / DocumentChunk / PipelineResult
  -> to_dict serialization for export/audit
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any


class DocumentType(str, Enum):
    OVERVIEW = "overview"
    QUICK_START = "quick_start"
    PARAMETER_REFERENCE = "parameter_reference"
    LIST = "list"

    @property
    def classification_description(self) -> str:
        descriptions = {
            DocumentType.OVERVIEW: "概述类。介绍背景、核心概念、整体架构、适用场景，不强调立即操作步骤。",
            DocumentType.QUICK_START: "快速上手类。包含前置条件、安装、初始化、运行示例、最短操作路径。",
            DocumentType.PARAMETER_REFERENCE: "参数说明类。围绕配置项、参数、字段、属性、取值范围、默认值展开。",
            DocumentType.LIST: "列表类。以清单、目录、能力列表、API/FAQ/资源索引等枚举内容为主。",
        }
        return descriptions[self]

    @property
    def router_aliases(self) -> tuple[str, ...]:
        aliases = {
            DocumentType.OVERVIEW: ("overview",),
            DocumentType.QUICK_START: ("quick_start", "quickstart"),
            DocumentType.PARAMETER_REFERENCE: ("parameter_reference", "parameter-reference"),
            DocumentType.LIST: ("list",),
        }
        return aliases[self]


@dataclass(slots=True)
class RawDocument:
    doc_id: str
    url: str
    title: str
    raw_content: str
    source: str
    fetched_at: str


@dataclass(slots=True)
class DocumentClassification:
    document_type: DocumentType
    confidence: float
    reasoning: str
    matched_signals: list[str]

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["document_type"] = self.document_type.value
        return data


@dataclass(slots=True)
class DocumentChunk:
    chunk_id: str
    doc_type: str
    chunk_type: str
    title: str
    url: str
    section_path: list[str]
    display_text: str
    retrieval_text: str
    structured_data: dict[str, Any] | None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class PipelineResult:
    run_id: str
    doc_id: str
    source: str
    url: str
    title: str
    raw_content: str
    preprocessed_content: str
    classification: DocumentClassification
    processed_content: str
    chunks: list[DocumentChunk]

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["classification"] = self.classification.to_dict()
        payload["chunks"] = [item.to_dict() for item in self.chunks]
        return payload

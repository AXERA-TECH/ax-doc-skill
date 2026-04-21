"""
Pulsar2 document preprocessing and section-chunking module.

This module performs the following stages in a fixed order:

1. Preprocessing (`preprocess_content`)
   - Input: raw Markdown text, which may include HTML, links, and RTD-generated anchors.
   - Steps:
     a) Normalize line endings and unescape HTML entities (for example, `&lt;` -> `<`).
     b) Remove URLs from Markdown links while keeping readable link text; also remove bare URLs.
     c) Strip HTML tags and collapse common line-break tags (`<br>`, `</p>`, etc.) into newlines.
     d) Remove the `### log 参考信息` section: drop content from that heading until the next
        heading at the same or higher level (`#`, `##`, or `###`).
     e) Collapse excessive blank lines and apply `strip()`.
   - Output: `preprocessed_content` for downstream routing, processing, and chunking.

2. Section chunking (`plan_chunks`)
   - Input: preprocessed Markdown text.
   - Rules:
     a) Only `#`, `##`, and `###` are treated as section boundaries.
     b) Exactly one chunk is produced per section (one section -> one chunk).
     c) `####` and deeper headings are not split into separate chunks; they stay in section body.
     d) `section_path` is maintained using a heading-level stack, for example:
        `["4. Quick Start", "4.3. Compile and Run", "4.3.2. Output File Notes"]`.
   - Output: a list of `DocumentChunk` objects while preserving stable field contracts
     (`chunk_id`, `chunk_type`, `retrieval_text`, etc.).

3. Retrieval text construction (`build_retrieval_text`)
   - Construct retrieval text from section metadata and section body.
   - Normalize Markdown table padding spaces in table rows for compact retrieval text.
"""

from __future__ import annotations

from dataclasses import dataclass
from html import unescape
import logging
import re
from typing import Any

from .models import DocumentChunk, DocumentType
from .utils import stable_hash


HEADING_RE = re.compile(r"^\s{0,3}(#{1,6})\s+(.*)$")
MARKDOWN_LINK_RE = re.compile(r"\[([^\]]+)\]\([^)]+\)")
RAW_URL_RE = re.compile(r"https?://[^\s)>\"']+|www\.[^\s)>\"']+", re.IGNORECASE)
HTML_TAG_RE = re.compile(r"<[^>]+>")
HTML_BREAK_RE = re.compile(r"<\s*(?:br|/p|/div|/li|/h\d)\s*/?>", re.IGNORECASE)
EXCESS_NEWLINES_RE = re.compile(r"\n{3,}")
TABLE_SEPARATOR_CELL_RE = re.compile(r":?-{3,}:?")
logger = logging.getLogger(__name__)


@dataclass(slots=True)
class Section:
    heading: str
    level: int
    section_path: list[str]
    body: str


def _normalize_raw_text(text: str) -> str:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    normalized = unescape(normalized)
    normalized = normalized.replace("\u00a0", " ").replace("\u200b", "")
    return "\n".join(line.rstrip() for line in normalized.splitlines())


def _strip_links_and_html(text: str) -> str:
    text = HTML_BREAK_RE.sub("\n", text)
    text = MARKDOWN_LINK_RE.sub(r"\1", text)
    text = RAW_URL_RE.sub("", text)
    text = HTML_TAG_RE.sub("", text)
    return text


def _is_log_reference_heading(line: str) -> bool:
    match = HEADING_RE.match(line)
    if not match:
        return False
    level = len(match.group(1))
    if level != 3:
        return False
    heading_text = _clean_heading_text(match.group(2))
    return "log 参考信息" in heading_text


def _remove_log_reference_sections(text: str) -> str:
    lines = text.splitlines()
    kept: list[str] = []
    idx = 0
    while idx < len(lines):
        line = lines[idx]
        if not _is_log_reference_heading(line):
            kept.append(line)
            idx += 1
            continue
        idx += 1
        while idx < len(lines):
            candidate = lines[idx]
            match = HEADING_RE.match(candidate)
            if match and len(match.group(1)) <= 3:
                break
            idx += 1
    return "\n".join(kept)


def preprocess_content(text: str) -> str:
    data = _normalize_raw_text(text)
    data = _strip_links_and_html(data)
    data = _remove_log_reference_sections(data)
    return EXCESS_NEWLINES_RE.sub("\n\n", data).strip()


def _clean_heading_text(text: str) -> str:
    cleaned = re.sub(r"\s*#+\s*$", "", text).strip()
    return cleaned.rstrip("#").strip()


def _is_markdown_table_row(line: str) -> bool:
    stripped = line.strip()
    return stripped.count("|") >= 2 and not stripped.startswith("#")


def _is_markdown_table_separator(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return False
    if stripped.startswith("|"):
        stripped = stripped[1:]
    if stripped.endswith("|"):
        stripped = stripped[:-1]
    cells = [cell.strip().replace(" ", "") for cell in stripped.split("|")]
    if not cells:
        return False
    return all(bool(TABLE_SEPARATOR_CELL_RE.fullmatch(cell)) for cell in cells)


def _split_table_row(line: str) -> list[str]:
    stripped = line.strip()
    if stripped.startswith("|"):
        stripped = stripped[1:]
    if stripped.endswith("|"):
        stripped = stripped[:-1]
    return [cell.strip() for cell in stripped.split("|")]


def _normalize_table_separator_cell(cell: str) -> str:
    normalized = cell.strip().replace(" ", "")
    if not normalized:
        return "---"
    left_aligned = normalized.startswith(":")
    right_aligned = normalized.endswith(":")
    dash_count = max(3, normalized.count("-"))
    return f"{':' if left_aligned else ''}{'-' * dash_count}{':' if right_aligned else ''}"


def _normalize_markdown_table_spacing(text: str) -> str:
    lines = text.splitlines()
    rewritten: list[str] = []
    idx = 0
    in_code_fence = False

    while idx < len(lines):
        line = lines[idx]
        stripped = line.strip()
        if stripped.startswith("```"):
            in_code_fence = not in_code_fence
            rewritten.append(line)
            idx += 1
            continue

        if (
            not in_code_fence
            and idx + 1 < len(lines)
            and _is_markdown_table_row(lines[idx])
            and _is_markdown_table_separator(lines[idx + 1])
        ):
            header_cells = _split_table_row(lines[idx])
            separator_cells = _split_table_row(lines[idx + 1])
            rewritten.append(f"|{'|'.join(header_cells)}|")
            rewritten.append(f"|{'|'.join(_normalize_table_separator_cell(cell) for cell in separator_cells)}|")
            idx += 2

            while idx < len(lines) and _is_markdown_table_row(lines[idx]):
                row_cells = _split_table_row(lines[idx])
                rewritten.append(f"|{'|'.join(row_cells)}|")
                idx += 1
            continue

        rewritten.append(line)
        idx += 1

    return "\n".join(rewritten)


def extract_sections(text: str) -> list[Section]:
    """Split content by markdown chapter headings: `#`, `##`, `###`."""
    sections: list[Section] = []
    stack: list[tuple[int, str]] = []

    current_heading = "document_root"
    current_level = 0
    current_path: list[str] = []
    current_lines: list[str] = []

    def flush() -> None:
        body = "\n".join(current_lines).strip()
        if current_heading == "document_root" and not body:
            return
        section_path = current_path[:] if current_path else ([current_heading] if current_heading != "document_root" else [])
        sections.append(
            Section(
                heading=current_heading,
                level=current_level,
                section_path=section_path,
                body=body,
            )
        )

    for line in text.splitlines():
        match = HEADING_RE.match(line)
        if not match:
            current_lines.append(line)
            continue

        heading_level = len(match.group(1))
        if heading_level > 3:
            # Level-4+ headings stay in current section body.
            current_lines.append(line)
            continue

        heading_text = _clean_heading_text(match.group(2))
        flush()

        while stack and stack[-1][0] >= heading_level:
            stack.pop()
        stack.append((heading_level, heading_text))

        current_heading = heading_text
        current_level = heading_level
        current_path = [item[1] for item in stack]
        current_lines = []

    flush()

    # If no chapter heading exists, keep one fallback chunk for full content.
    if not any(section.level > 0 for section in sections):
        raw = text.strip()
        if raw:
            return [Section(heading="document", level=0, section_path=["document"], body=raw)]
        return []

    return [section for section in sections if section.level > 0 and section.body]


def _chunk_id(document_type: DocumentType, title: str, section_path: list[str], chunk_type: str, order: int, text: str) -> str:
    base = f"{document_type.value}|{title}|{'/'.join(section_path)}|{chunk_type}|{order}|{text[:120]}"
    return stable_hash(base, 12)


def _make_chunk(
    *,
    document_type: DocumentType,
    chunk_type: str,
    title: str,
    url: str,
    section_path: list[str],
    display_text: str,
    structured_data: dict[str, Any] | None,
    metadata: dict[str, Any],
    order: int,
) -> DocumentChunk:
    chunk = DocumentChunk(
        chunk_id=_chunk_id(document_type, title, section_path, chunk_type, order, display_text),
        doc_type=document_type.value,
        chunk_type=chunk_type,
        title=title,
        url=url,
        section_path=section_path,
        display_text=display_text.strip(),
        retrieval_text="",
        structured_data=structured_data,
        metadata=metadata,
    )
    chunk.retrieval_text = build_retrieval_text(chunk)
    return chunk


def build_retrieval_text(chunk: DocumentChunk) -> str:
    section = " > ".join(chunk.section_path) if chunk.section_path else "(root)"
    normalized_content = _normalize_markdown_table_spacing(chunk.display_text)
    parts = [
        f"标题: {chunk.title}",
        f"来源: {chunk.url}",
        f"章节: {section}",
    ]
    parts.append("内容:")
    parts.append(normalized_content)
    return "\n".join(parts).strip()


def plan_chunks(*, document_type: DocumentType, title: str, url: str, processed_content: str) -> list[DocumentChunk]:
    logger.debug("Planning chunks by chapter headings. title='%s', doc_type='%s'.", title, document_type.value)
    sections = extract_sections(processed_content)
    chunks: list[DocumentChunk] = []

    for idx, section in enumerate(sections, start=1):
        chunks.append(
            _make_chunk(
                document_type=document_type,
                chunk_type="section_overview",
                title=title,
                url=url,
                section_path=section.section_path,
                display_text=section.body,
                structured_data=None,
                metadata={"heading": section.heading, "heading_level": section.level},
                order=idx,
            )
        )

    logger.info(
        "Chunk planning completed. title='%s', doc_type='%s', sections=%d, chunks=%d.",
        title,
        document_type.value,
        len(sections),
        len(chunks),
    )
    return chunks

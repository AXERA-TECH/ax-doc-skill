"""
Flow
----
document_type processor
  -> overview_function: compress command/log-heavy long fences
  -> quick_start_function: remove log noise in code context
  -> parameter_reference_function: keep table structure, drop terminal noise
  -> list_function: keep list order, dedupe adjacent duplicates
"""

from __future__ import annotations

from collections import deque
import logging
import re

from .models import DocumentType

LIST_ITEM_RE = re.compile(r"^\s*(?:[-*+]|\d+[.)]|[A-Za-z][.)])\s+")
TABLE_SEPARATOR_RE = re.compile(r"^\s*\|?(?:\s*:?-{3,}:?\s*\|)+\s*$")
LOG_LINE_RE = re.compile(
    r"\b(?:INFO|WARNING|WARN|ERROR|DEBUG|TRACE|CRITICAL|FATAL)\b|"
    r"(?:\d{4}[-/]\d{2}[-/]\d{2}[ T]\d{2}:\d{2}:\d{2})",
    re.IGNORECASE,
)

LONG_CODE_FENCE_RE = re.compile(r"(```[\s\S]*?```)", re.MULTILINE)
COMMAND_HINT_RE = re.compile(r"^\s*(?:\$ |# |python\d?(?:\.\d+)?\b|pip\d?(?:\.\d+)?\b|bash\b|sh\b)")
LOG_HINT_RE = re.compile(
    r"\b(?:INFO|WARNING|WARN|ERROR|DEBUG|TRACE|CRITICAL|FATAL)\b|"
    r"(?:\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2})",
    re.IGNORECASE,
)

LOG_LEVEL_RE = re.compile(r"\b(?:INFO|WARNING|WARN|ERROR|ERR|DEBUG|TRACE|CRITICAL|FATAL)\b", re.IGNORECASE)
TIMESTAMP_RE = re.compile(
    r"(?:\d{4}[-/]\d{2}[-/]\d{2}[ T]\d{2}:\d{2}:\d{2}(?:[.,]\d+)?)|"
    r"(?:\d{2}:\d{2}:\d{2}(?:[.,]\d+)?)"
)
TRACEBACK_RE = re.compile(r"^\s*(?:Traceback \(most recent call last\):|File \".*\", line \d+|[A-Za-z_]\w*Error:)")
PROMPT_RE = re.compile(r"^\s*(?:>>> |\.\.\. |\$ |# |root@|[\w.-]+@[\w.-]+:)")
CODE_KEYWORD_RE = re.compile(
    r"^\s*(?:import |from |def |class |for |if |while |with |return |export |set |cd |mkdir |cp |mv |python\d?(?:\.\d+)?\b|pip\d?(?:\.\d+)?\b|bash\b|sh\b)"
)
FILE_LIKE_RE = re.compile(r"\b[\w./-]+\.(?:py|bin|onnx|json|yaml|yml|txt|log|so|axmodel|md)\b")
SECTION_HINT_RE = re.compile(r"(?:示例(?:代码|命令|输出|日志)?|命令示例|运行示例|输出示例|日志示例|执行结果|运行结果|控制台输出|终端输出)", re.IGNORECASE)
PROGRESS_RE = re.compile(r"(?:\b\d{1,3}%\b.*(?:\||/|it/s|s/it|ETA))|(?:[=>-]{8,})|(?:█{4,})", re.IGNORECASE)
logger = logging.getLogger(__name__)


def overview_function(text: str) -> str:
    def replace_block(match: re.Match[str]) -> str:
        block = match.group(1)
        lines = block.splitlines()
        if len(lines) <= 14:
            return block
        body = [line for line in lines[1:-1] if line.strip()]
        command_like = sum(1 for line in body if COMMAND_HINT_RE.match(line))
        log_like = sum(1 for line in body if LOG_HINT_RE.search(line))
        if command_like + log_like < max(4, len(body) // 3):
            return block
        return "\n".join(lines[:6] + ["..."] + lines[-3:])

    cleaned = LONG_CODE_FENCE_RE.sub(replace_block, text)
    result = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
    logger.debug("overview_function processed text: input=%d, output=%d.", len(text), len(result))
    return result


def _looks_like_code_line(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return False
    if line.startswith("    ") or line.startswith("\t"):
        return True
    if stripped.startswith("```"):
        return True
    if PROMPT_RE.match(line) or CODE_KEYWORD_RE.match(line):
        return True
    if FILE_LIKE_RE.search(stripped):
        return True
    if re.match(r"^\s*[\w.-]+\s*=\s*.+$", line):
        return True
    return bool(re.match(r"^\s*(?:./|/)?[\w./-]+(?:\s+[-\w./:=]+)+\s*$", stripped))


def _is_log_line(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return False
    if TRACEBACK_RE.match(stripped) or LOG_LEVEL_RE.search(stripped):
        return True
    if TIMESTAMP_RE.search(stripped):
        return True
    return bool(PROGRESS_RE.search(stripped))


def quick_start_function(text: str) -> str:
    lines = text.splitlines()
    cleaned: list[str] = []
    in_fenced = False
    recent: deque[str] = deque(maxlen=3)
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("```"):
            in_fenced = not in_fenced
            cleaned.append(line)
            recent.append(stripped)
            continue
        prev_nonempty = next((x.strip() for x in reversed(lines[:i]) if x.strip()), "")
        next_nonempty = next((x.strip() for x in lines[i + 1 :] if x.strip()), "")
        section_hint = SECTION_HINT_RE.search(" ".join([*recent, next_nonempty])) is not None
        code_context = in_fenced or _looks_like_code_line(line) or _looks_like_code_line(prev_nonempty) or _looks_like_code_line(next_nonempty) or section_hint
        if code_context and _is_log_line(line):
            continue
        cleaned.append(line)
        if stripped:
            recent.append(stripped)
    result = re.sub(r"\n{3,}", "\n\n", "\n".join(cleaned)).strip()
    logger.debug("quick_start_function processed text: input=%d, output=%d.", len(text), len(result))
    return result


def parameter_reference_function(text: str) -> str:
    normalized: list[str] = []
    for line in text.splitlines():
        if TABLE_SEPARATOR_RE.match(line):
            normalized.append(line.strip())
        elif "|" in line:
            cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
            normalized.append("| " + " | ".join(cells) + " |")
        else:
            normalized.append(line.rstrip())
    cleaned = [line for line in normalized if not (line.strip() and LOG_LINE_RE.search(line) and "|" not in line)]
    result = re.sub(r"\n{3,}", "\n\n", "\n".join(cleaned)).strip()
    logger.debug("parameter_reference_function processed text: input=%d, output=%d.", len(text), len(result))
    return result


def list_function(text: str) -> str:
    cleaned: list[str] = []
    prev_item = ""
    for line in text.splitlines():
        stripped = line.strip()
        if LIST_ITEM_RE.match(stripped):
            normalized_item = re.sub(r"^\s*(?:[-*+]|\d+[.)]|[A-Za-z][.)])\s+", "", stripped)
            if normalized_item == prev_item:
                continue
            prev_item = normalized_item
        elif stripped:
            prev_item = ""
        cleaned.append(line.rstrip())
    result = re.sub(r"\n{3,}", "\n\n", "\n".join(cleaned)).strip()
    logger.debug("list_function processed text: input=%d, output=%d.", len(text), len(result))
    return result


PROCESSOR_MAP = {
    DocumentType.OVERVIEW.value: overview_function,
    DocumentType.QUICK_START.value: quick_start_function,
    DocumentType.PARAMETER_REFERENCE.value: parameter_reference_function,
    DocumentType.LIST.value: list_function,
}

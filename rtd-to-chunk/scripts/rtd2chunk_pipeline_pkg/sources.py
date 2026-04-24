"""Offline and GitHub markdown loaders."""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from .common import make_doc_id, utc_now_iso
from .models import RawDocument


TITLE_LINE_RE = re.compile(r"^Title:\s*(.+?)\s*$", re.MULTILINE)
URL_LINE_RE = re.compile(r"^URL Source:\s*(.+?)\s*$", re.MULTILINE)
logger = logging.getLogger(__name__)
GITHUB_API_BASE = "https://api.github.com"


def derive_title_and_url(raw_markdown: str, fallback_path: Path | None = None) -> tuple[str, str]:
    title_match = TITLE_LINE_RE.search(raw_markdown)
    url_match = URL_LINE_RE.search(raw_markdown)
    h1_match = re.search(r"^\s*#\s+(.+?)\s*$", raw_markdown, flags=re.MULTILINE)
    fallback_title = fallback_path.stem if fallback_path else "unknown_title"
    title = title_match.group(1).strip() if title_match else (h1_match.group(1).strip() if h1_match else fallback_title)
    url = url_match.group(1).strip() if url_match else f"local://{fallback_title}"
    return title, url


def load_offline_documents(input_dir: Path, glob_pattern: str = "*.md") -> list[RawDocument]:
    docs: list[RawDocument] = []
    logger.info("Loading offline documents from '%s' with pattern '%s'.", input_dir, glob_pattern)
    for path in sorted(input_dir.glob(glob_pattern)):
        if not path.is_file():
            continue
        raw = path.read_text(encoding="utf-8")
        title, url = derive_title_and_url(raw, fallback_path=path)
        docs.append(
            RawDocument(
                doc_id=make_doc_id(title, url, raw),
                url=url,
                title=title,
                raw_content=raw,
                source="offline_md",
                fetched_at=utc_now_iso(),
            )
        )
    logger.info("Loaded offline documents count=%d.", len(docs))
    return docs


def _http_get_text(url: str, timeout: float = 30.0) -> str:
    req = Request(
        url,
        headers={
            "User-Agent": "rtd2chunk-pipeline/1.0",
            "Accept": "application/vnd.github+json, text/plain;q=0.9, */*;q=0.8",
        },
    )
    with urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")


def _parse_github_repo_url(url: str) -> tuple[str, str, str | None, str]:
    parsed = urlparse(url)
    if parsed.netloc != "github.com":
        raise ValueError(f"Only github.com URLs are supported, got: {url}")

    segments = [segment for segment in parsed.path.split("/") if segment]
    if len(segments) < 2:
        raise ValueError(f"Invalid GitHub repository URL: {url}")
    owner, repo = segments[0], segments[1]
    branch: str | None = None
    sub_path = ""

    if len(segments) >= 4 and segments[2] in {"tree", "blob"}:
        branch = segments[3]
        if len(segments) > 4:
            sub_path = "/".join(segments[4:])

    return owner, repo, branch, sub_path


def _resolve_default_branch(owner: str, repo: str, timeout: float) -> str:
    api_url = f"{GITHUB_API_BASE}/repos/{owner}/{repo}"
    payload = _http_get_text(api_url, timeout=timeout)
    data = json.loads(payload)
    default_branch = str(data.get("default_branch") or "").strip()
    if not default_branch:
        raise RuntimeError(f"Cannot resolve default branch for {owner}/{repo}")
    return default_branch


def _list_markdown_paths(owner: str, repo: str, branch: str, sub_path: str, timeout: float) -> list[str]:
    api_url = f"{GITHUB_API_BASE}/repos/{owner}/{repo}/git/trees/{branch}?recursive=1"
    payload = _http_get_text(api_url, timeout=timeout)
    data = json.loads(payload)
    tree = data.get("tree")
    if not isinstance(tree, list):
        raise RuntimeError(f"Unexpected GitHub tree response for {owner}/{repo}@{branch}")

    normalized_prefix = sub_path.strip("/")
    markdown_paths: list[str] = []
    for node in tree:
        if not isinstance(node, dict):
            continue
        if node.get("type") != "blob":
            continue
        path = str(node.get("path", ""))
        if not path.lower().endswith(".md"):
            continue
        if normalized_prefix and not path.startswith(normalized_prefix.rstrip("/") + "/") and path != normalized_prefix:
            continue
        markdown_paths.append(path)
    return sorted(markdown_paths)


def _load_single_github_markdown(owner: str, repo: str, branch: str, file_path: str, timeout: float) -> RawDocument | None:
    raw_url = f"https://raw.githubusercontent.com/{owner}/{repo}/{branch}/{file_path}"
    page_url = f"https://github.com/{owner}/{repo}/blob/{branch}/{file_path}"
    try:
        raw = _http_get_text(raw_url, timeout=timeout)
    except Exception:
        logger.warning("Failed to fetch markdown from GitHub: %s", raw_url, exc_info=True)
        return None

    title, _ = derive_title_and_url(raw, fallback_path=Path(file_path))
    return RawDocument(
        doc_id=make_doc_id(title, page_url, raw),
        url=page_url,
        title=title,
        raw_content=raw,
        source="github_rtd",
        fetched_at=utc_now_iso(),
    )


def load_github_rtd_documents(urls: list[str], timeout: float = 30.0) -> list[RawDocument]:
    docs: list[RawDocument] = []
    for url in urls:
        owner, repo, branch, sub_path = _parse_github_repo_url(url)
        if not branch:
            try:
                branch = _resolve_default_branch(owner, repo, timeout=timeout)
            except Exception:
                logger.warning(
                    "Failed to resolve default branch for %s/%s, fallback to 'main'.",
                    owner,
                    repo,
                    exc_info=True,
                )
                branch = "main"
        logger.info(
            "Loading GitHub RTD markdowns. owner='%s', repo='%s', branch='%s', path='%s'.",
            owner,
            repo,
            branch,
            sub_path or "/",
        )
        markdown_paths = _list_markdown_paths(owner, repo, branch, sub_path, timeout=timeout)
        if not markdown_paths:
            logger.warning("No markdown files found for GitHub URL: %s", url)
            continue
        loaded_for_url = 0
        for file_path in markdown_paths:
            doc = _load_single_github_markdown(owner, repo, branch, file_path, timeout=timeout)
            if doc is not None:
                docs.append(doc)
                loaded_for_url += 1
        logger.info(
            "Loaded markdown files from GitHub URL: selected=%d, fetched=%d, url=%s",
            len(markdown_paths),
            loaded_for_url,
            url,
        )
    if not docs:
        raise RuntimeError("No markdown documents loaded from GitHub URLs.")
    logger.info("Loaded GitHub URL documents count=%d.", len(docs))
    return docs

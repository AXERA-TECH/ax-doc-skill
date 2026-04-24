"""
Flow
----
helpers
  -> hash/id generation
  -> utc timestamp
  -> json read/write
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def stable_hash(text: str, length: int = 12) -> str:
    return hashlib.md5(text.encode("utf-8")).hexdigest()[:length]


def make_doc_id(title: str, url: str, raw_content: str) -> str:
    seed = f"{title}|{url}|{raw_content[:200]}"
    return stable_hash(seed, length=16)


def dump_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

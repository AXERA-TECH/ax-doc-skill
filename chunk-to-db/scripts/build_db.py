#!/usr/bin/env python3
"""Build LanceDB from rtd-to-chunk outputs."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

import lancedb

LANGUAGE='Chinese'

def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="build_db")
    parser.add_argument("--input-dir", required=True, help="Directory containing chunk JSON outputs.")
    parser.add_argument("--db-dir", required=True, help="LanceDB directory.")
    parser.add_argument("--table", required=True, help="Target table name.")
    parser.add_argument(
        "--mode",
        choices=("overwrite", "append"),
        default="overwrite",
        help="Write mode. overwrite recreates table; append inserts into existing table.",
    )
    parser.add_argument(
        "--embedding-provider",
        choices=("none", "openai"),
        default="none",
        help="Embedding provider. none means BM25-only index.",
    )
    parser.add_argument(
        "--embedding-model",
        default="text-embedding-3-small",
        help="Embedding model name used when provider=openai.",
    )
    parser.add_argument(
        "--embedding-batch-size",
        type=int,
        default=64,
        help="Batch size for embedding API calls.",
    )
    parser.add_argument(
        "--vector-column",
        default="vector",
        help="Column name used for embedding vectors.",
    )
    return parser.parse_args()


def _json_str(value: Any) -> str:
    if value is None:
        return "{}"
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    if isinstance(value, list):
        return json.dumps(value, ensure_ascii=False)
    return json.dumps({"value": value}, ensure_ascii=False)


def _load_rows(input_dir: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for file_path in sorted(input_dir.rglob("*.json")):
        if file_path.name.startswith("_"):
            continue

        payload = json.loads(file_path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            continue
        chunks = payload.get("chunks")
        if not isinstance(chunks, list):
            continue

        doc_id = str(payload.get("doc_id", file_path.stem))
        title = str(payload.get("title", ""))
        url = str(payload.get("url", ""))

        classification = payload.get("classification") if isinstance(payload.get("classification"), dict) else {}
        doc_type = str(classification.get("document_type", payload.get("doc_type", "unknown")))

        for chunk in chunks:
            if not isinstance(chunk, dict):
                continue

            section_path = chunk.get("section_path")
            if isinstance(section_path, list):
                section_path_text = " > ".join(str(item) for item in section_path)
            else:
                section_path_text = str(section_path or "")

            retrieval_text = str(chunk.get("retrieval_text", "") or chunk.get("display_text", ""))
            row = {
                "chunk_id": str(chunk.get("chunk_id", "")),
                "doc_id": doc_id,
                "title": title,
                "url": url,
                "doc_type": doc_type,
                "chunk_type": str(chunk.get("chunk_type", "")),
                "section_path": section_path_text,
                "display_text": str(chunk.get("display_text", "")),
                "retrieval_text": retrieval_text,
                "metadata_json": _json_str(chunk.get("metadata", {})),
                "structured_data_json": _json_str(chunk.get("structured_data", {})),
                "source_file": str(file_path),
            }
            rows.append(row)
    return rows


def _build_openai_embedder(model: str):
    try:
        from openai import OpenAI
    except Exception as exc:
        raise RuntimeError("openai package is required for --embedding-provider openai") from exc

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is required for --embedding-provider openai")

    # Optional: point to a compatible endpoint (self-hosted, gateway, etc.).
    base_url = os.getenv("OPENAI_BASE_URL")

    # Alternatively, you can use this code to integrate your own embedding model.
    # Please keep your API key secure and avoid leakage.

    # api_key="sk-xx"
    # base_url="https://api.example.cn/v1"
    # model="Qwen/Qwen3-Embedding-8B"
    # logging.warning("Please keep your API key secure and avoid leakage.")

    if base_url:
        client = OpenAI(api_key=api_key, base_url=base_url)
    else:
        client = OpenAI(api_key=api_key)
    
    def _embed_many(texts: list[str]) -> list[list[float]]:
        response = client.embeddings.create(model=model, input=texts)
        return [item.embedding for item in response.data]

    return _embed_many


def _attach_vectors(
    *,
    rows: list[dict[str, Any]],
    provider: str,
    model: str,
    batch_size: int,
    vector_column: str,
) -> tuple[int, int | None]:
    """Attach embedding vectors to each row **in-place**.

    Behavior:
    - Reads `retrieval_text` from each row and batches embedding requests.
    - Writes the returned vector into `row[vector_column]`.
    - Returns `(embedded_count, vector_dim)`.

    Mutation semantics:
    - `rows` is a mutable list of mutable dict objects.
    - This function mutates those dicts in-place, so callers holding the same
      `rows` reference (or references to the same row dicts) will observe the
      new vector field after this function returns.
    """
    if provider == "none":
        return 0, None

    if batch_size <= 0:
        raise RuntimeError("--embedding-batch-size must be > 0")

    embed_many = _build_openai_embedder(model)

    vector_dim: int | None = None
    embedded_count = 0
    for start in range(0, len(rows), batch_size):
        batch = rows[start : start + batch_size]
        texts = [str(item.get("retrieval_text", "")) for item in batch]
        vectors = embed_many(texts)
        if len(vectors) != len(batch):
            raise RuntimeError("embedding response size mismatch")

        for row, vector in zip(batch, vectors, strict=True):
            row[vector_column] = vector
            embedded_count += 1
            if vector_dim is None:
                vector_dim = len(vector)

    return embedded_count, vector_dim


def _create_or_append_table(*, db: Any, table_name: str, rows: list[dict[str, Any]], mode: str) -> Any:
    """Create a table or append rows depending on mode and table existence.

    Behavior:
    - `overwrite`: always recreate `table_name` with `rows`.
    - otherwise: detect whether the table already exists; append rows when it
      does, or create a new table when it does not.

    Compatibility:
    - Normalizes multiple LanceDB metadata/listing return shapes
      (`list_tables`/`table_names`) before existence checks.
    """
    if mode == "overwrite":
        return db.create_table(table_name, data=rows, mode="overwrite")

    if hasattr(db, "list_tables"):
        raw_tables: Any = db.list_tables()
    else:
        raw_tables = db.table_names()

    if isinstance(raw_tables, dict):
        table_names = set(str(item) for item in raw_tables.get("tables", []))
    elif isinstance(raw_tables, list) and raw_tables and all(
        isinstance(item, tuple) and len(item) == 2 for item in raw_tables
    ):
        kv = {str(k): v for k, v in raw_tables}
        table_names = set(str(item) for item in kv.get("tables", []))
    else:
        normalized = list(raw_tables)
        if normalized and all(isinstance(item, tuple) and len(item) == 2 for item in normalized):
            kv = {str(k): v for k, v in normalized}
            table_names = set(str(item) for item in kv.get("tables", []))
        else:
            table_names = set(str(item) for item in normalized)
    if table_name in table_names:
        table = db.open_table(table_name)
        table.add(rows)
        return table

    return db.create_table(table_name, data=rows, mode="create")


def _create_fts_index(table: Any) -> None:
    """Create FTS index with Chinese-first settings, then English fallback.

    Logic:
    - Prioritize Chinese-oriented indexing when `LANGUAGE` is Chinese.
    - If that fails (unsupported language/options/version), retry with English.
    - For each language, try advanced kwargs first, then a reduced kwargs set
      for older LanceDB signatures.
    """
    configured = LANGUAGE.strip()
    normalized = configured.lower()
    if normalized in {"chinese", "zh", "zh-cn", "zh_cn"}:
        language_candidates = ["Chinese", "English"]
    elif normalized in {"english", "en", "en-us", "en_us"}:
        language_candidates = ["English", "Chinese"]
    else:
        language_candidates = [configured, "Chinese", "English"]

    seen: set[str] = set()
    ordered_candidates: list[str] = []
    for candidate in language_candidates:
        key = candidate.lower()
        if key in seen:
            continue
        seen.add(key)
        ordered_candidates.append(candidate)

    last_exc: Exception | None = None
    for language in ordered_candidates:
        is_english = language.lower() == "english"
        is_chinese = language.lower() == "chinese"
        if is_chinese:
            # Chinese-first preset from product requirement.
            advanced_kwargs: dict[str, Any] = {
                "columns": "retrieval_text",
                "language": "Chinese",
                "with_position": True,
                "remove_stop_words": True,
                "lower_case": True,
                "stem": False,
                "ascii_folding": False,
                "replace": True,
            }
        else:
            advanced_kwargs = {
                "columns": "retrieval_text",
                "language": language,
                "stem": is_english,
                "ascii_folding": is_english,
                "replace": True,
                "use_tantivy": True,
                "with_position": True,
                "remove_stop_words": is_english,
            }
            if is_english:
                advanced_kwargs["base_tokenizer"] = "simple"

        try:
            table.create_fts_index(**advanced_kwargs)
            return
        except Exception as exc:
            last_exc = exc

        try:
            table.create_fts_index(
                "retrieval_text",
                language=language,
                stem=is_english,
                ascii_folding=is_english,
                replace=True,
            )
            return
        except Exception as exc:
            last_exc = exc

    try:
        table.create_fts_index("retrieval_text", replace=True)
    except Exception:
        if last_exc is not None:
            raise last_exc
        raise


def main() -> int:
    """Build/update a LanceDB table from chunk JSON rows.

    Processing logic:
    - Parse CLI args and resolve input/output directories.
    - Validate `input_dir` and load chunk rows from disk.
    - Optionally attach embedding vectors (in-place) based on configured
      provider/model/batch settings.
    - Ensure `db_dir` exists, connect to LanceDB, then create/append table
      data according to `--mode`.
    - Attempt to create a full-text index on `retrieval_text`; continue even
      if index creation fails.
    - Print a JSON summary for downstream scripts and return exit code 0.
    """
    args = _parse_args()
    input_dir = Path(args.input_dir).resolve()
    db_dir = Path(args.db_dir).resolve()

    if not input_dir.exists() or not input_dir.is_dir():
        raise SystemExit(f"input dir not found: {input_dir}")

    rows = _load_rows(input_dir)
    if not rows:
        raise SystemExit(f"no chunk rows discovered under: {input_dir}")

    embedded_count, vector_dim = _attach_vectors(
        rows=rows,
        provider=args.embedding_provider,
        model=args.embedding_model,
        batch_size=args.embedding_batch_size,
        vector_column=args.vector_column,
    )

    db_dir.mkdir(parents=True, exist_ok=True)
    db = lancedb.connect(str(db_dir))
    table = _create_or_append_table(db=db, table_name=args.table, rows=rows, mode=args.mode)

    try:
        _create_fts_index(table)
        index_msg = "created"
    except Exception as exc:  # pragma: no cover
        index_msg = f"skipped ({exc})"

    print(
        json.dumps(
            {
                "status": "ok",
                "input_dir": str(input_dir),
                "db_dir": str(db_dir),
                "table": args.table,
                "rows_written": len(rows),
                "embedding_provider": args.embedding_provider,
                "embedded_rows": embedded_count,
                "vector_column": args.vector_column if embedded_count else "",
                "vector_dim": vector_dim,
                "fts_index": index_msg,
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

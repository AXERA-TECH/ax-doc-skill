#!/usr/bin/env python3
"""Serve or inspect LanceDB for chunk retrieval."""

from __future__ import annotations

import argparse
import atexit
import hashlib
import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any

import lancedb


LOGGER = logging.getLogger("chunk_to_db.server_db")


def _setup_logging(*, level: str, log_file: str) -> None:
    log_level = getattr(logging, level.upper(), logging.INFO)
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        handlers=[logging.StreamHandler()],
    )


def _acquire_stdio_singleton_lock(db_dir: Path, table: str):
    """Ensure only one stdio server process runs for the same db/table pair."""
    try:
        import fcntl
    except Exception as exc:  # pragma: no cover
        raise RuntimeError("fcntl is required for --stdio singleton lock on this platform") from exc

    key = f"{db_dir.resolve()}::{table}"
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]
    lock_path = Path("/tmp") / f"chunk_to_db_server_db_{digest}.lock"
    lock_file = lock_path.open("w", encoding="utf-8")
    lock_file.write(f"{os.getpid()}\n")
    lock_file.flush()

    try:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError as exc:
        lock_file.close()
        raise RuntimeError(
            "another --stdio server is already running for this db/table"
        ) from exc

    def _release() -> None:
        try:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
        except Exception:
            pass
        try:
            lock_file.close()
        except Exception:
            pass

    atexit.register(_release)
    return lock_file


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="server_db")
    parser.add_argument("--db-dir", default="assets/pulsar2_rtd", help="LanceDB directory.")
    parser.add_argument("--table", default='pulsar2-doc', help="Table name.")
    parser.add_argument(
        "--action",
        choices=("health", "list-tables", "fts-search", "vector-search", "hybrid-search"),
        default="health",
        help="Single action mode.",
    )
    parser.add_argument("--query", default="", help="Query text.")
    parser.add_argument("--limit", type=int, default=5, help="Result limit.")
    parser.add_argument("--vector-column", default="vector", help="Vector column name.")
    parser.add_argument(
        "--embedding-provider",
        choices=("none", "openai"),
        default="none",
        help="Embedding provider used by vector/hybrid search.",
    )
    parser.add_argument(
        "--embedding-model",
        default="text-embedding-3-small",
        help="Embedding model name used when provider=openai.",
    )
    parser.add_argument(
        "--alpha",
        type=float,
        default=0.8,
        help="Hybrid fusion weight for vector branch. 0 means FTS-only, 1 means vector-only.",
    )
    parser.add_argument("--rrf-k", type=float, default=60.0, help="RRF denominator constant.")
    parser.add_argument(
        "--log-level",
        choices=("DEBUG", "INFO", "WARNING", "ERROR"),
        default="INFO",
        help="Logging level.",
    )
    parser.add_argument("--stdio", action="store_true", help="Read line-delimited JSON requests from stdin.")
    return parser.parse_args()


def _connect(db_dir: Path) -> Any:
    if not db_dir.exists() or not db_dir.is_dir():
        raise FileNotFoundError(f"db dir not found: {db_dir}")
    LOGGER.info("Connecting LanceDB: db_dir=%s", db_dir)
    return lancedb.connect(str(db_dir))


def _list_tables(db: Any) -> list[str]:
    """Return normalized table names across LanceDB API variants."""
    raw: Any
    if hasattr(db, "list_tables"):
        raw = db.list_tables()
    else:
        raw = db.table_names()

    if isinstance(raw, dict):
        tables = raw.get("tables", [])
        if isinstance(tables, list):
            return [str(item) for item in tables]
        return []

    if isinstance(raw, list):
        if raw and all(isinstance(item, tuple) and len(item) == 2 for item in raw):
            kv = {str(k): v for k, v in raw}
            tables = kv.get("tables", [])
            if isinstance(tables, list):
                return [str(item) for item in tables]
            return []
        return [str(item) for item in raw]

    normalized = list(raw)
    if normalized and all(isinstance(item, tuple) and len(item) == 2 for item in normalized):
        kv = {str(k): v for k, v in normalized}
        tables = kv.get("tables", [])
        if isinstance(tables, list):
            return [str(item) for item in tables]
        return []
    return [str(item) for item in normalized]


def _build_openai_embedder(model: str):
    try:
        from openai import OpenAI
    except Exception as exc:
        raise RuntimeError("openai package is required for provider=openai") from exc

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is required for provider=openai")

    # Optional: point to a compatible endpoint (self-hosted, gateway, etc.).
    base_url = os.getenv("OPENAI_BASE_URL")
    # Alternatively, you can use this code to integrate your own embedding model. Please keep your API key secure and avoid leakage.
    # OPENAI_API_KEY="sk-xxx"
    # OPENAI_BASE_URL="https://example.com/v1"
    # OPENAI_EMBEDDING_MODEL="Qwen/Qwen3-Embedding-4B"
    # api_key=OPENAI_API_KEY
    # base_url=OPENAI_BASE_URL
    # model=OPENAI_EMBEDDING_MODEL
    if base_url:
        client = OpenAI(api_key=api_key, base_url=base_url)
    else:
        client = OpenAI(api_key=api_key)
    
    def _embed_one(text: str) -> list[float]:
        response = client.embeddings.create(model=model, input=[text])
        return response.data[0].embedding

    return _embed_one


def _select_fields(df: Any) -> list[dict[str, Any]]:
    cols = [
        col
        for col in (
            "chunk_id",
            "doc_id",
            "title",
            "chunk_type",
            "retrieval_text",
            "_distance",
            "_score",
        )
        if col in df.columns
    ]
    if not cols:
        return []
    return df[cols].to_dict(orient="records")


def _health(db: Any, table_name: str, vector_column: str) -> dict[str, Any]:
    tables = _list_tables(db)
    if table_name not in tables:
        return {"status": "error", "message": f"table not found: {table_name}", "tables": tables}

    table = db.open_table(table_name)
    try:
        sample = table.limit(1).to_pandas()
    except Exception:
        sample = table.to_pandas().head(1)
    columns = list(sample.columns)
    return {
        "status": "ok",
        "table": table_name,
        "tables": tables,
        "sample_rows": int(sample.shape[0]),
        "has_retrieval_text": "retrieval_text" in columns,
        "has_vector": vector_column in columns,
        "vector_column": vector_column,
    }


def _fts_search(db: Any, table_name: str, query: str, limit: int) -> dict[str, Any]:
    if not query.strip():
        return {"status": "error", "message": "query is required for fts-search"}

    tables = _list_tables(db)
    if table_name not in tables:
        return {"status": "error", "message": f"table not found: {table_name}", "tables": tables}

    started = time.perf_counter()
    table = db.open_table(table_name)
    results = table.search(query, query_type="fts").limit(limit).to_pandas()
    elapsed_ms = (time.perf_counter() - started) * 1000
    LOGGER.info("FTS search done: table=%s limit=%d rows=%d elapsed_ms=%.2f", table_name, limit, int(results.shape[0]), elapsed_ms)
    return {"status": "ok", "count": int(results.shape[0]), "records": _select_fields(results)}


def _vector_search(
    db: Any,
    table_name: str,
    query: str,
    limit: int,
    *,
    vector_column: str,
    provider: str,
    model: str,
) -> dict[str, Any]:
    if not query.strip():
        return {"status": "error", "message": "query is required for vector-search"}
    if provider == "none":
        return {"status": "error", "message": "set --embedding-provider openai for vector-search"}

    tables = _list_tables(db)
    if table_name not in tables:
        return {"status": "error", "message": f"table not found: {table_name}", "tables": tables}

    embed_one = _build_openai_embedder(model)
    query_vector = embed_one(query)

    started = time.perf_counter()
    table = db.open_table(table_name)
    try:
        results = table.search(query_vector, vector_column_name=vector_column).limit(limit).to_pandas()
    except TypeError:
        results = table.search(query_vector).limit(limit).to_pandas()
    elapsed_ms = (time.perf_counter() - started) * 1000
    LOGGER.info("Vector search done: table=%s limit=%d rows=%d elapsed_ms=%.2f", table_name, limit, int(results.shape[0]), elapsed_ms)
    return {"status": "ok", "count": int(results.shape[0]), "records": _select_fields(results)}


def _ranked(records: list[dict[str, Any]]) -> dict[str, tuple[int, dict[str, Any]]]:
    ranked: dict[str, tuple[int, dict[str, Any]]] = {}
    for idx, item in enumerate(records, start=1):
        doc_id = str(item.get("doc_id", ""))
        chunk_id = str(item.get("chunk_id", ""))
        key = f"{doc_id}::{chunk_id}" if doc_id or chunk_id else f"row-{idx}"
        ranked[key] = (idx, item)
    return ranked


def _hybrid_search(
    db: Any,
    table_name: str,
    query: str,
    limit: int,
    *,
    vector_column: str,
    provider: str,
    model: str,
    alpha: float,
    rrf_k: float,
) -> dict[str, Any]:
    if not query.strip():
        return {"status": "error", "message": "query is required for hybrid-search"}
    if provider == "none":
        return {"status": "error", "message": "set --embedding-provider openai for hybrid-search"}
    if alpha < 0.0 or alpha > 1.0:
        return {"status": "error", "message": "--alpha must be within [0, 1]"}
    if rrf_k <= 0.0:
        return {"status": "error", "message": "--rrf-k must be > 0"}

    fts_payload = _fts_search(db, table_name, query, limit * 3)
    if fts_payload.get("status") != "ok":
        return fts_payload

    vector_payload = _vector_search(
        db,
        table_name,
        query,
        limit * 3,
        vector_column=vector_column,
        provider=provider,
        model=model,
    )
    if vector_payload.get("status") != "ok":
        return vector_payload

    fts_ranked = _ranked(fts_payload.get("records", []))
    vector_ranked = _ranked(vector_payload.get("records", []))

    all_ids = set(fts_ranked.keys()) | set(vector_ranked.keys())
    fused: list[dict[str, Any]] = []
    for key in all_ids:
        score = 0.0
        base_record: dict[str, Any]

        if key in vector_ranked:
            vector_rank, record = vector_ranked[key]
            base_record = dict(record)
            score += alpha * (1.0 / (rrf_k + float(vector_rank)))
        else:
            base_record = {}

        if key in fts_ranked:
            fts_rank, fts_record = fts_ranked[key]
            if not base_record:
                base_record = dict(fts_record)
            score += (1.0 - alpha) * (1.0 / (rrf_k + float(fts_rank)))

        base_record["hybrid_score"] = score
        fused.append(base_record)

    fused.sort(key=lambda item: float(item.get("hybrid_score", 0.0)), reverse=True)
    top = fused[:limit]
    LOGGER.info(
        "Hybrid search done: table=%s limit=%d fts_candidates=%d vector_candidates=%d fused=%d",
        table_name,
        limit,
        len(fts_payload.get("records", [])),
        len(vector_payload.get("records", [])),
        len(top),
    )
    return {"status": "ok", "count": len(top), "records": top}


def _run_action(
    db: Any,
    action: str,
    table: str,
    query: str,
    limit: int,
    *,
    vector_column: str,
    provider: str,
    model: str,
    alpha: float,
    rrf_k: float,
) -> dict[str, Any]:
    LOGGER.debug("Run action: action=%s table=%s query_len=%d limit=%d", action, table, len(query), limit)
    if limit <= 0:
        return {"status": "error", "message": "--limit must be > 0"}
    if action == "list-tables":
        return {"status": "ok", "tables": _list_tables(db)}
    if action == "fts-search":
        return _fts_search(db, table, query, limit)
    if action == "vector-search":
        return _vector_search(
            db,
            table,
            query,
            limit,
            vector_column=vector_column,
            provider=provider,
            model=model,
        )
    if action == "hybrid-search":
        return _hybrid_search(
            db,
            table,
            query,
            limit,
            vector_column=vector_column,
            provider=provider,
            model=model,
            alpha=alpha,
            rrf_k=rrf_k,
        )
    if action == "health":
        return _health(db, table, vector_column)
    return {"status": "error", "message": f"unknown action: {action}"}


def _stdio_loop(
    db: Any,
    default_table: str,
    *,
    vector_column: str,
    provider: str,
    model: str,
    alpha: float,
    rrf_k: float,
) -> int:
    LOGGER.info("STDIO loop started: default_table=%s", default_table)
    for line in sys.stdin:
        payload_text = line.strip()
        if not payload_text:
            continue
        try:
            payload = json.loads(payload_text)
            action = str(payload.get("action", "health"))
            table = str(payload.get("table", default_table))
            query = str(payload.get("query", ""))
            limit = int(payload.get("limit", 5))
            response = _run_action(
                db,
                action=action,
                table=table,
                query=query,
                limit=limit,
                vector_column=vector_column,
                provider=provider,
                model=model,
                alpha=alpha,
                rrf_k=rrf_k,
            )
        except Exception as exc:  # pragma: no cover
            LOGGER.exception("STDIO request failed")
            response = {"status": "error", "message": str(exc)}

        print(json.dumps(response, ensure_ascii=False), flush=True)
    LOGGER.info("STDIO loop ended")
    return 0


def main() -> int:
    args = _parse_args()
    _setup_logging(level=args.log_level, log_file="")
    LOGGER.info(
        "server_db started: db_dir=%s table=%s action=%s stdio=%s",
        args.db_dir,
        args.table,
        args.action,
        args.stdio,
    )
    db_dir = Path(args.db_dir).resolve()
    if args.stdio:
        _acquire_stdio_singleton_lock(db_dir, args.table)
    db = _connect(db_dir)
    if args.stdio:
        return _stdio_loop(
            db,
            args.table,
            vector_column=args.vector_column,
            provider=args.embedding_provider,
            model=args.embedding_model,
            alpha=args.alpha,
            rrf_k=args.rrf_k,
        )

    response = _run_action(
        db,
        action=args.action,
        table=args.table,
        query=args.query,
        limit=args.limit,
        vector_column=args.vector_column,
        provider=args.embedding_provider,
        model=args.embedding_model,
        alpha=args.alpha,
        rrf_k=args.rrf_k,
    )
    print(json.dumps(response, ensure_ascii=False))
    LOGGER.info("server_db finished: status=%s", response.get("status"))
    return 0 if response.get("status") == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())

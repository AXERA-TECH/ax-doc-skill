#!/usr/bin/env python3
"""Build Pulsar2 chunk DB pipeline.

Pipeline:
1) Run rtd-to-chunk/scripts/chunk.py against Pulsar2 docs repo URL.
2) Run chunk-to-db/scripts/build_db.py to rebuild LanceDB into pulsar2-doc-search/assets.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path


DEFAULT_REPO_URL = "https://github.com/AXERA-TECH/pulsar2-docs"
DEFAULT_TABLE = "pulsar2-doc"
DEFAULT_DB_SUBDIR = "pulsar2_rtd"


def _now_tag() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def _run(cmd: list[str], cwd: Path) -> None:
    print(f"$ (cwd={cwd}) {' '.join(cmd)}", flush=True)
    proc = subprocess.run(cmd, cwd=str(cwd))
    if proc.returncode != 0:
        raise SystemExit(proc.returncode)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="build_pulsar2_db_pipeline")
    parser.add_argument("--repo-url", default=DEFAULT_REPO_URL, help="GitHub repository/tree URL for rtd-to-chunk.")
    parser.add_argument(
        "--run-id",
        default=f"pulsar2_build_{_now_tag()}",
        help="Run ID used for rtd-to-chunk output directory.",
    )
    parser.add_argument("--max-concurrency", type=int, default=4, help="Max concurrency for rtd-to-chunk.")
    parser.add_argument("--log-level", default="INFO", help="Log level for rtd-to-chunk, e.g. DEBUG/INFO/WARNING.")
    parser.add_argument(
        "--chunk-output-root",
        default=None,
        help="Optional override for rtd-to-chunk output root. Defaults to rtd-to-chunk/scripts/tmp.",
    )
    parser.add_argument(
        "--embedding-provider",
        choices=("none", "openai"),
        default="openai",
        help="Embedding provider for build_db.",
    )
    parser.add_argument("--embedding-model", default="text-embedding-3-small", help="Embedding model for build_db.")
    parser.add_argument("--table", default=DEFAULT_TABLE, help="LanceDB table name.")
    parser.add_argument(
        "--db-subdir",
        default=DEFAULT_DB_SUBDIR,
        help="Subdirectory under pulsar2-doc-search/assets to store LanceDB.",
    )
    parser.add_argument(
        "--keep-existing-db",
        action="store_true",
        help="Do not delete existing db dir before build (still uses --mode overwrite).",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    root = Path(__file__).resolve().parent

    execute_py = root / "rtd-to-chunk" / "scripts" / "chunk.py"
    build_db_py = root / "chunk-to-db" / "scripts" / "build_db.py"

    output_root = Path(args.chunk_output_root) if args.chunk_output_root else (root / "rtd-to-chunk" / "scripts" / "tmp")
    chunk_output_dir = output_root / args.run_id

    assets_root = root / "pulsar2-doc-search" / "assets"
    db_dir = assets_root / args.db_subdir

    if not execute_py.exists():
        raise SystemExit(f"missing script: {execute_py}")
    if not build_db_py.exists():
        raise SystemExit(f"missing script: {build_db_py}")

    output_root.mkdir(parents=True, exist_ok=True)
    assets_root.mkdir(parents=True, exist_ok=True)

    rtd_cmd = [
        sys.executable,
        str(execute_py),
        "--input-url",
        args.repo_url,
        "--output-dir",
        str(output_root),
        "--log-level",
        args.log_level,
        "--max-concurrency",
        str(args.max_concurrency),
        "--run-id",
        args.run_id,
    ]

    _run(rtd_cmd, root)

    if not chunk_output_dir.exists() or not chunk_output_dir.is_dir():
        raise SystemExit(f"chunk output dir missing: {chunk_output_dir}")

    json_files = [p for p in chunk_output_dir.glob("*.json") if not p.name.startswith("_")]
    if not json_files:
        raise SystemExit(f"no chunk JSON files found under: {chunk_output_dir}")

    if db_dir.exists() and not args.keep_existing_db:
        print(f"Removing existing DB directory: {db_dir}", flush=True)
        shutil.rmtree(db_dir)

    build_cmd = [
        sys.executable,
        str(build_db_py),
        "--input-dir",
        str(chunk_output_dir),
        "--db-dir",
        str(db_dir),
        "--table",
        args.table,
        "--mode",
        "overwrite",
        "--embedding-provider",
        args.embedding_provider,
        "--embedding-model",
        args.embedding_model,
    ]

    _run(build_cmd, root)

    print("\\nPipeline completed.", flush=True)
    print(f"repo_url: {args.repo_url}", flush=True)
    print(f"run_id: {args.run_id}", flush=True)
    print(f"chunk_output_dir: {chunk_output_dir}", flush=True)
    print(f"db_dir: {db_dir}", flush=True)
    print(f"table: {args.table}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

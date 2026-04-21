"""CLI runner for execute."""

from __future__ import annotations

import argparse
import asyncio
import logging
from pathlib import Path

from .logging_utils import setup_logging
from .models import RawDocument
from .pipeline import run_pipeline_batch
from .source_adapters import load_github_rtd_documents, load_offline_documents
from .utils import dump_json, utc_now_iso

logger = logging.getLogger(__name__)


def _dedupe_documents(documents: list[RawDocument]) -> list[RawDocument]:
    deduped: list[RawDocument] = []
    seen_doc_ids: set[str] = set()
    duplicate_count = 0
    for doc in documents:
        if doc.doc_id in seen_doc_ids:
            duplicate_count += 1
            logger.warning("Duplicate document dropped: doc_id='%s', title='%s'.", doc.doc_id, doc.title)
            continue
        seen_doc_ids.add(doc.doc_id)
        deduped.append(doc)
    if duplicate_count:
        logger.info("Document dedupe applied: input=%d, kept=%d, dropped=%d.", len(documents), len(deduped), duplicate_count)
    return deduped


def _load_documents(*, input_dir: str | None, input_urls: list[str] | None, glob_pattern: str) -> list[RawDocument]:
    if input_urls:
        docs = load_github_rtd_documents(input_urls)
        logger.info("Loaded %d URL document(s) from GitHub input URLs.", len(docs))
        return _dedupe_documents(docs)
    if not input_dir:
        raise ValueError("Either input_dir or input_url is required.")
    input_path = Path(input_dir)
    docs = load_offline_documents(input_path, glob_pattern=glob_pattern)
    logger.info("Loaded %d offline documents from '%s' with pattern '%s'.", len(docs), input_path, glob_pattern)
    return _dedupe_documents(docs)


async def _run_execute(args: argparse.Namespace) -> None:
    logger.info("Execute command started.")
    run_id = args.run_id or f"run-{utc_now_iso().replace(':', '').replace('-', '')[:15]}"
    output_dir = Path(args.output_dir) / run_id
    documents = _load_documents(input_dir=args.input_dir, input_urls=args.input_url, glob_pattern=args.glob)
    logger.info("Running pipeline for run_id='%s' with %d documents.", run_id, len(documents))
    results = await run_pipeline_batch(
        run_id=run_id,
        documents=documents,
        output_dir=output_dir,
        max_concurrency=args.max_concurrency,
        router_mode=args.router_mode,
        llm_model=args.llm_model,
    )
    summary = {
        "run_id": run_id,
        "total_documents": len(results),
        "output_dir": str(output_dir),
    }
    dump_json(output_dir / "_run_summary.json", summary)
    logger.info("Execute command completed. Output: '%s'.", output_dir)
    print(summary)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="rtd2chunk-pipeline")
    sub = parser.add_subparsers(dest="command", required=True)

    execute = sub.add_parser("execute")
    execute.add_argument("--log-level", required=False, help="Logging level, e.g. DEBUG/INFO/WARNING.")
    source_group = execute.add_mutually_exclusive_group(required=True)
    source_group.add_argument("--input-dir", required=False, help="Offline markdown input directory.")
    source_group.add_argument(
        "--input-url",
        action="append",
        required=False,
        help="GitHub repository/tree URL to fetch markdown files. Can be provided multiple times.",
    )
    execute.add_argument("--output-dir", required=True, help="Output root directory.")
    execute.add_argument("--glob", default="*.md", help="Input file glob pattern.")
    execute.add_argument("--max-concurrency", type=int, default=4, help="Max concurrent document tasks.")
    execute.add_argument(
        "--router-mode",
        choices=("rule", "llm"),
        default="rule",
        help="Document router mode.",
    )
    execute.add_argument(
        "--llm-model",
        required=False,
        help="LLM model name used only when router mode is llm.",
    )
    execute.add_argument("--run-id", required=False)
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    if args.max_concurrency <= 0:
        parser.error("--max-concurrency must be a positive integer")
    setup_logging(args.log_level)
    asyncio.run(_run_execute(args))


if __name__ == "__main__":
    main()

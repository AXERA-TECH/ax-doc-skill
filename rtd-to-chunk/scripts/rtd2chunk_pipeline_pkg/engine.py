"""Batch and document pipeline orchestration."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from .pulsar2_chunking import plan_chunks, preprocess_content
from .common import dump_json
from .models import PipelineResult, RawDocument
from .rules import PROCESSOR_MAP, rule_based_classify

logger = logging.getLogger(__name__)


async def run_pipeline_for_document(
    *,
    run_id: str,
    raw_document: RawDocument,
    output_dir: Path,
) -> PipelineResult:
    doc_id = raw_document.doc_id
    logger.info("Start processing doc_id='%s', title='%s'.", doc_id, raw_document.title)

    preprocessed = preprocess_content(raw_document.raw_content)
    logger.debug("Using rule-based classifier for title='%s'.", raw_document.title)
    classification = rule_based_classify(raw_document.title, preprocessed)

    processor = PROCESSOR_MAP[classification.document_type.value]
    processed = processor(preprocessed)
    chunks = plan_chunks(
        document_type=classification.document_type,
        title=raw_document.title,
        url=raw_document.url,
        processed_content=processed,
    )
    result = PipelineResult(
        run_id=run_id,
        doc_id=doc_id,
        source=raw_document.source,
        url=raw_document.url,
        title=raw_document.title,
        raw_content=raw_document.raw_content,
        preprocessed_content=preprocessed,
        classification=classification,
        processed_content=processed,
        chunks=chunks,
    )
    dump_json(output_dir / f"{raw_document.doc_id}.json", result.to_dict())
    logger.info(
        "Finished doc_id='%s'. type='%s', chunks=%d.",
        doc_id,
        classification.document_type.value,
        len(chunks),
    )
    return result


async def run_pipeline_batch(
    *,
    run_id: str,
    documents: list[RawDocument],
    output_dir: Path,
    max_concurrency: int = 4,
) -> list[PipelineResult]:
    logger.info(
        "Batch run started. run_id='%s', documents=%d, max_concurrency=%d.",
        run_id,
        len(documents),
        max(1, max_concurrency),
    )
    semaphore = asyncio.Semaphore(max(1, max_concurrency))
    output_dir.mkdir(parents=True, exist_ok=True)

    async def run_one(item: RawDocument) -> PipelineResult:
        async with semaphore:
            try:
                return await run_pipeline_for_document(
                    run_id=run_id,
                    raw_document=item,
                    output_dir=output_dir,
                )
            except Exception:
                logger.exception("Document failed in batch. run_id='%s', doc_id='%s'.", run_id, item.doc_id)
                raise

    results = await asyncio.gather(*(run_one(item) for item in documents))
    logger.info("Batch run completed. run_id='%s', results=%d.", run_id, len(results))
    return results

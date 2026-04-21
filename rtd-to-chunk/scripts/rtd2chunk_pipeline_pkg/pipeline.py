# Pipeline Flow
# RawDocument
#   |
#   v
# preprocess_content(raw_content)
#   |
#   v
# classify_document(title, preprocessed, router_mode)
#   |                         \
#   | rule_based_classify      \ llm_classify (fallback to rule)
#   v
# PROCESSOR_MAP[document_type](preprocessed)
#   |
#   v
# plan_chunks(document_type, title, url, processed_content)
#   |
#   v
# PipelineResult(...)
#   |
#   v
# dump_json(output_dir/{doc_id}.json)

"""Pipeline execution for document chunking."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Literal

from .models import DocumentClassification, PipelineResult, RawDocument
from .processors import PROCESSOR_MAP
from .router import llm_classify, rule_based_classify
from .pulsar2_chunker import plan_chunks, preprocess_content
from .utils import dump_json

logger = logging.getLogger(__name__)


async def classify_document(
    *,
    title: str,
    content: str,
    router_mode: Literal["rule", "llm"] = "rule",
    llm_model: str | None = None,
) -> DocumentClassification:
    if router_mode == "rule":
        logger.debug("Using rule-based classifier for title='%s'.", title)
        return rule_based_classify(title, content)
    try:
        return await llm_classify(title, content, model=llm_model)
    except Exception:
        logger.warning("LLM classifier failed, fallback to rule-based classifier for title='%s'.", title, exc_info=True)
        return rule_based_classify(title, content)


async def run_pipeline_for_document(
    *,
    run_id: str,
    raw_document: RawDocument,
    output_dir: Path,
    router_mode: Literal["rule", "llm"] = "rule",
    llm_model: str | None = None,
) -> PipelineResult:
    doc_id = raw_document.doc_id
    logger.info("Start processing doc_id='%s', title='%s'.", doc_id, raw_document.title)

    preprocessed = preprocess_content(raw_document.raw_content)

    classification = await classify_document(
        title=raw_document.title,
        content=preprocessed,
        router_mode=router_mode,
        llm_model=llm_model,
    )

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
    router_mode: Literal["rule", "llm"] = "rule",
    llm_model: str | None = None,
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
                    router_mode=router_mode,
                    llm_model=llm_model,
                )
            except Exception:
                logger.exception("Document failed in batch. run_id='%s', doc_id='%s'.", run_id, item.doc_id)
                raise

    results = await asyncio.gather(*(run_one(item) for item in documents))
    logger.info("Batch run completed. run_id='%s', results=%d.", run_id, len(results))
    return results

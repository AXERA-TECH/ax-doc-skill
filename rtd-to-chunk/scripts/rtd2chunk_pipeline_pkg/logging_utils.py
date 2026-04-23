from __future__ import annotations

import logging
import os


def setup_logging(level: str | None = None) -> None:
    resolved = (level or os.getenv("RTD2CHUNK_LOG_LEVEL", "INFO")).upper()
    log_level = getattr(logging, resolved, logging.INFO)
    root_logger = logging.getLogger()
    if root_logger.handlers:
        root_logger.setLevel(log_level)
        return
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )
    logging.captureWarnings(True)

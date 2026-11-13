"""Logowanie modułu.

Standalone (`examples/*`): wywołaj `setup_logging()` → handler na stderr.
Wpięcie w pipeline: NIE wywołuj nic — logger `"yt-upload"` ma domyślnie
zero handlerów, więc rekordy propagują do loggera hosta (ClippyMe/n8n runner
sam zdecyduje o formacie i destination).
"""
from __future__ import annotations

import logging
import sys

LOGGER_NAME = "yt-upload"


def get_logger() -> logging.Logger:
    """Zwraca wspólny logger modułu (bez handlerów — patrz docstring modułu)."""
    return logging.getLogger(LOGGER_NAME)


def setup_logging(level: int = logging.INFO, stream=None) -> logging.Logger:
    """Podpina StreamHandler (standalone usage). Idempotentne."""
    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(level)
    if not logger.handlers:
        handler = logging.StreamHandler(stream or sys.stderr)
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)-7s [yt-upload] %(message)s")
        )
        logger.addHandler(handler)
    logger.propagate = False
    return logger

"""File logging for every entrypoint (CLI / serve / gui).

One rotating log file (1MB x 3 = max ~3MB, D1 decision) in the config dir:
~/.config/bookfetch/bookfetch.log  (override with $BOOKFETCH_CONFIG).

Entrypoints call setup_logging() once at start; the bookfetch logger is then
available everywhere (n2core, sources, server) for diagnostics. Errors shown to
end users stay friendly; the full traceback lives here.
"""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

_LOG_NAME = "bookfetch"
_LOG_FILE = "bookfetch.log"
_MAX_BYTES = 1_000_000
_BACKUP_COUNT = 2  # bookfetch.log + 2 rotated = ~3MB total

_configured: Path | None = None


def log_path() -> Path | None:
    """Path of the active log file, or None before setup_logging()."""
    return _configured


def setup_logging(cfg_dir: Path, level: int = logging.INFO) -> Path:
    """Attach a rotating file handler to the 'bookfetch' logger (idempotent)."""
    global _configured
    if _configured is not None:
        return _configured
    cfg_dir.mkdir(parents=True, exist_ok=True)
    path = cfg_dir / _LOG_FILE
    handler = RotatingFileHandler(
        path, maxBytes=_MAX_BYTES, backupCount=_BACKUP_COUNT, encoding="utf-8")
    handler.setFormatter(logging.Formatter(
        "%(asctime)s %(levelname)s %(name)s: %(message)s"))
    logger = logging.getLogger(_LOG_NAME)
    logger.setLevel(level)
    logger.addHandler(handler)
    logger.propagate = False  # don't double-print through root handlers
    _configured = path
    logging.getLogger(_LOG_NAME).info("log started: %s", path)
    return path

"""
Structured Logging Configuration using structlog.

Outputs JSON Lines (JSONL) directly to `logs/agent.jsonl` while optionally
printing human-readable or structured log events to stderr/stdout.

Log Schema Contract for Research & Evaluation:
  timestamp: ISO-8601 UTC timestamp
  event: Event identifier (e.g. 'memory_write', 'memory_read', 'tool_call', 'agent_turn')
  level: info / warning / error
  session_id: Active session identifier
  source: Origin source string
  trust_tier: Classification tier
  [optional payload fields]: tool_name, tool_args, memory_id, content_hash, memory_type
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Optional

import structlog


_LOGGER_INITIALIZED = False


class FlushFileHandler(logging.FileHandler):
    """FileHandler that flushes after each emission to guarantee immediate persistence for testing/auditing."""
    def emit(self, record: logging.LogRecord) -> None:
        super().emit(record)
        self.flush()


def setup_logging(logs_dir: str = "logs", log_filename: str = "agent.jsonl") -> structlog.stdlib.BoundLogger:
    """
    Initialize structlog pipeline to write JSONL to `logs/agent.jsonl`.
    Thread-safe and idempotent.
    """
    global _LOGGER_INITIALIZED
    log_dir_path = Path(logs_dir)
    log_dir_path.mkdir(parents=True, exist_ok=True)
    jsonl_file_path = (log_dir_path / log_filename).resolve()

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)

    # Add FlushFileHandler if not already registered for this file
    already_added = any(
        isinstance(h, logging.FileHandler) and getattr(h, "baseFilename", None) == str(jsonl_file_path)
        for h in root_logger.handlers
    )
    if not already_added:
        file_handler = FlushFileHandler(str(jsonl_file_path), encoding="utf-8")
        file_handler.setLevel(logging.INFO)
        root_logger.addHandler(file_handler)

    # Configure structlog
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.JSONRenderer(),
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=False,
    )

    _LOGGER_INITIALIZED = True
    return structlog.get_logger("memory_poisoning_lab")


def get_logger(name: Optional[str] = None) -> structlog.stdlib.BoundLogger:
    """Retrieve configured structlog instance."""
    if not _LOGGER_INITIALIZED:
        setup_logging()
    return structlog.get_logger(name or "memory_poisoning_lab")

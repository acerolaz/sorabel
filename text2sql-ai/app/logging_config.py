"""Logging wiring for the audit trail required by E3/E5: every generation call must be
journalized with its identity, its requested resource and its decision. The use case
attaches those as `extra=` fields on the LogRecord, which the default uvicorn formatter
silently drops — hence this JSON formatter.

Only the structured audit fields below are emitted: never a raw LLM or judge response
beyond its structured verdict — see ../../.claude/rules/security.md."""

from __future__ import annotations

import json
import logging
from logging.config import dictConfig
from typing import Any

AUDIT_FIELDS = ("profile", "allowed_tables", "question", "sql", "outcome", "attempts")


class JsonLogFormatter(logging.Formatter):
    """Renders a LogRecord as a single-line JSON object, promoting the audit fields
    attached via `extra=` to top-level keys."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": self.formatTime(record),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for field in AUDIT_FIELDS:
            if hasattr(record, field):
                payload[field] = getattr(record, field)
        if record.exc_info is not None:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, default=str)


def configure_logging(level: str = "INFO") -> None:
    """Install the JSON formatter on the root logger. `disable_existing_loggers` stays
    False so uvicorn's own loggers keep working, and `app.*` loggers keep propagating
    to root rather than owning a handler of their own."""
    dictConfig(
        {
            "version": 1,
            "disable_existing_loggers": False,
            "formatters": {"json": {"()": JsonLogFormatter}},
            "handlers": {
                "stdout": {
                    "class": "logging.StreamHandler",
                    "stream": "ext://sys.stdout",
                    "formatter": "json",
                }
            },
            "root": {"handlers": ["stdout"], "level": level},
        }
    )

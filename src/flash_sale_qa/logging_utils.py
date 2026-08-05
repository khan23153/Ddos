from __future__ import annotations

import json
import logging
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "event": getattr(record, "event", "log"),
            "message": record.getMessage(),
        }
        for field in (
            "account",
            "product",
            "order_id",
            "attempt",
            "status",
            "duration_ms",
            "error_type",
        ):
            value = getattr(record, field, None)
            if value is not None:
                payload[field] = value
        return json.dumps(payload, ensure_ascii=False, default=str)


def configure_logging(log_dir: str) -> logging.Logger:
    Path(log_dir).mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("flash_sale_qa")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()

    formatter = JsonFormatter()
    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(formatter)
    logger.addHandler(console)

    filename = Path(log_dir) / datetime.now(UTC).strftime("qa-%Y%m%d.jsonl")
    file_handler = logging.FileHandler(filename, encoding="utf-8")
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    return logger


def log_event(
    logger: logging.Logger,
    level: int,
    event: str,
    message: str,
    **fields: Any,
) -> None:
    logger.log(level, message, extra={"event": event, **fields})

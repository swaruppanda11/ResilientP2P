import logging
import sys
from typing import Any

from common.schemas import LogEvent


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        event_name = getattr(record, "event_name", record.getMessage())
        details = getattr(record, "details", {})
        event = LogEvent(
            service=getattr(record, "service_name", record.name),
            level=record.levelname,
            event=event_name,
            details=details,
        )
        if hasattr(event, "model_dump_json"):
            return event.model_dump_json()
        return event.json()


def get_logger(service_name: str) -> logging.Logger:
    logger = logging.getLogger(service_name)
    if logger.handlers:
        return logger

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    return logger


def log_event(logger: logging.Logger, level: int, event_name: str, **details: Any) -> None:
    logger.log(level, event_name, extra={"event_name": event_name, "details": details})

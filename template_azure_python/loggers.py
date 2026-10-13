import json
import logging
from datetime import UTC, datetime
from threading import Lock

from opentelemetry import trace

_lock = Lock()


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        context = trace.get_current_span().get_span_context()
        event = {
            "timestamp": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "trace_id": f"{context.trace_id:032x}" if context.is_valid else None,
            "span_id": f"{context.span_id:016x}" if context.is_valid else None,
        }
        return json.dumps(event, ensure_ascii=False)


def configure_logging(log_level: str = "INFO") -> None:
    """Configure one owned root handler without removing host/test/SDK handlers."""
    with _lock:
        root = logging.getLogger()
        root.setLevel(log_level)
        if not any(getattr(handler, "_template_json", False) for handler in root.handlers):
            handler = logging.StreamHandler()
            handler.setFormatter(JsonFormatter())
            handler._template_json = True  # type: ignore[attr-defined]
            root.addHandler(handler)
        for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
            logger = logging.getLogger(name)
            logger.handlers.clear()
            logger.propagate = True


def get_logger(
    name: str = "default",
    log_level: str | None = None,
) -> logging.Logger:
    """Return a propagating logger; root configuration is explicit at startup."""
    logger = logging.getLogger(name)
    if log_level is not None:
        logger.setLevel(log_level)
    return logger

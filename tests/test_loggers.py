import json
import logging

from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider

from template_azure_python.loggers import JsonFormatter, configure_logging, get_logger

logger = get_logger(__name__)


def test_get_logger(caplog):
    """
    Test the get_logger function to ensure it returns a logger instance
    and prints a debug message correctly.
    """
    logger.info("[TEST] Running test_get_logger")
    with caplog.at_level(logging.DEBUG):
        test_logger = get_logger(__name__)
        test_logger.setLevel(logging.DEBUG)
        test_logger.debug(f"{__name__} logger initialized")

    assert test_logger.name == __name__
    assert f"{__name__} logger initialized" in caplog.text
    assert "DEBUG" in caplog.text
    assert "test_loggers.py" in caplog.text


def test_configuration_is_idempotent_and_get_logger_has_no_handlers():
    configure_logging()
    configure_logging()
    assert sum(bool(getattr(handler, "_template_json", False)) for handler in logging.getLogger().handlers) == 1
    assert get_logger("test.structured").handlers == []
    assert get_logger("test.structured").propagate


def test_json_formatter_correlates_trace_and_span():
    provider = TracerProvider()
    record = logging.LogRecord("test", logging.INFO, __file__, 1, "Hello\n%s", ("World",), None)
    with provider.get_tracer("test").start_as_current_span("request"):
        context = trace.get_current_span().get_span_context()
        event = json.loads(JsonFormatter().format(record))
    assert event["message"] == "Hello\nWorld"
    assert event["trace_id"] == f"{context.trace_id:032x}"
    assert event["span_id"] == f"{context.span_id:016x}"
    provider.shutdown()

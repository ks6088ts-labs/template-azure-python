import logging
from unittest.mock import patch

from template_azure_python.loggers import get_logger

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


def test_get_logger_leaves_handlers_to_the_host(caplog):
    name = "template_azure_python.tests.host_logging"
    with patch.object(logging.getLogger(name), "handlers", []):
        first = get_logger(name)
        assert get_logger(name) is first
        assert first.handlers == []
        with caplog.at_level(logging.INFO):
            first.info("One record")
        assert [record.message for record in caplog.records].count("One record") == 1


def test_get_logger_supports_explicit_level():
    name = "template_azure_python.tests.explicit_level"
    with patch.object(logging.getLogger(name), "level", logging.NOTSET):
        assert get_logger(name, log_level="DEBUG").level == logging.DEBUG

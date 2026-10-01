import logging

import pytest

from template_python.core import hello_world
from template_python.loggers import get_logger

logger = get_logger(__name__)


@pytest.fixture(scope="session")
def setup_session():
    """
    Session-wide setup fixture that initializes resources
    needed for the tests. This fixture runs once per test session.
    It can be used to set up resources that are shared across multiple tests.
    """
    logger.info("[SETUP] Starting session-wide setup")
    resource = {"key": "value"}
    yield resource
    logger.info("[TEARDOWN] Cleaning up session-wide resources")


def test_hello_world_logs_message(caplog):
    """
    Test that hello_world logs the expected message at INFO level.
    """
    logger.info("[TEST] Running test_hello_world_logs_message")
    with caplog.at_level(logging.INFO, logger="template_python.core"):
        hello_world()
    assert "Hello World" in caplog.text


@pytest.mark.parametrize(
    "log_level",
    [
        logging.DEBUG,
        logging.INFO,
    ],
)
def test_hello_world_parametrized(caplog, log_level):
    """
    Parametrized test for the hello_world function.
    The message 'Hello World' should appear when capturing at INFO or lower.
    """
    logger.info(f"[TEST] Running test_hello_world_parametrized with log_level={log_level}")
    with caplog.at_level(log_level, logger="template_python.core"):
        hello_world()
    assert "Hello World" in caplog.text

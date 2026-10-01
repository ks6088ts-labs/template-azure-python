import logging

from template_python.loggers import get_logger

logger = get_logger(__name__)


def hello_world():
    """Log a greeting message"""
    logger.critical("Critical: Hello World")
    logger.error("Error: Hello World")
    logger.warning("Warning: Hello World")
    logger.info("Info: Hello World")
    logger.debug("Debug: Hello World")


if __name__ == "__main__":
    logger.setLevel(logging.DEBUG)
    hello_world()

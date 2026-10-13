import logging

LOG_FORMAT = "%(asctime)s [%(levelname)8s] %(message)s (%(filename)s:%(lineno)s)"


def get_logger(
    name: str = "default",
    log_level: str | None = None,
) -> logging.Logger:
    """Get a logger; entrypoints own handlers and the default logging level."""
    logger = logging.getLogger(name)
    if log_level is not None:
        logger.setLevel(log_level)
    return logger

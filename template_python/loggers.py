import logging

from template_python.settings import get_project_settings


def get_logger(
    name: str = "default",
    log_level: str | None = None,
) -> logging.Logger:
    """
    Get a logger with the specified name.

    If the logger already has handlers, it is returned as-is to avoid
    adding duplicate handlers on repeated calls.

    Args:
        name (str): The name of the logger.
        log_level (str | None): The logging level. Defaults to the project setting.
    Returns:
        logging.Logger: Configured logger instance.
    """
    logger = logging.getLogger(name)

    # Avoid adding duplicate handlers on repeated calls
    if logger.handlers:
        return logger

    if log_level is None:
        log_level = get_project_settings().project_log_level

    logger.setLevel(log_level)
    formatter = logging.Formatter("%(asctime)s [%(levelname)8s] %(message)s (%(filename)s:%(lineno)s)")
    handler = logging.StreamHandler()
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    return logger

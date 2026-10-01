from logging import DEBUG

from dotenv import load_dotenv

from template_python.loggers import get_logger
from template_python.settings import ProjectSettings

logger = get_logger(__name__)


def test_settings(caplog):
    """
    Test that ProjectSettings loads values correctly from the .env.template file.
    """
    logger.info("[TEST] Running test_settings")
    with caplog.at_level(DEBUG):
        assert load_dotenv(
            dotenv_path=".env.template",
            verbose=True,
        ), "Failed to load environment variables from .env.template"
        settings = ProjectSettings()
        assert settings.project_name == "template-python", "Default project name should be 'template-python'"
        logger.debug(f"ProjectSettings initialized: {settings}")

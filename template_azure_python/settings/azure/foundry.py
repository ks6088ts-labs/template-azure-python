from pydantic_settings import SettingsConfigDict

from template_azure_python.settings.azure._base import AzureServiceSettings


class FoundrySettings(AzureServiceSettings):
    endpoint: str | None = None

    model_config = SettingsConfigDict(env_prefix="FOUNDRY_PROJECT_")

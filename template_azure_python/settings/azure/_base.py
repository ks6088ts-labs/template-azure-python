from pydantic_settings import SettingsConfigDict

from template_azure_python.settings._base import EnvironmentSettings


class AzureServiceSettings(EnvironmentSettings):
    model_config = SettingsConfigDict(env_ignore_empty=True, populate_by_name=True)

from typing import Any

from pydantic_settings import SettingsConfigDict

from template_azure_python.settings._base import EnvironmentSettings


class AzureServiceSettings(EnvironmentSettings):
    model_config = SettingsConfigDict(env_ignore_empty=True)

    def __init__(self, **data: Any) -> None:
        # Keep constructor field names without enabling unrelated environment aliases.
        for name, field in type(self).model_fields.items():
            alias = field.validation_alias
            if isinstance(alias, str) and name in data and alias not in data:
                data[alias] = data.pop(name)
        super().__init__(**data)

from collections.abc import Callable

from pydantic_settings import BaseSettings, SettingsConfigDict


class FreshSettings[T]:
    def __init__(self, load: Callable[[], T]) -> None:
        self._load = load

    def __call__(self) -> T:
        return self._load()

    def cache_clear(self) -> None:
        """Preserve the cached-getter API without retaining stale settings."""


class EnvironmentSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        hide_input_in_errors=True,
        frozen=True,
    )

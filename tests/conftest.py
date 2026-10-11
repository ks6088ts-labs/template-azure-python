import os
from collections.abc import Generator
from pathlib import Path

import duckdb
import pytest

from template_azure_python.settings import AzureSettings, ProjectSettings, get_azure_settings, get_project_settings

pytest_plugins = ["pytester"]


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption("--run-llm-evals", action="store_true", default=False, help="Allow paid local LLM evaluations")


def pytest_configure(config: pytest.Config) -> None:
    enabled = config.getoption("--run-llm-evals")
    if enabled and not config.option.collectonly and (os.environ.get("CI") or os.environ.get("GITHUB_ACTIONS")):
        raise pytest.UsageError("Live LLM evaluations are local-only; CI may only use --collect-only.")
    directory = config.rootpath / "tests" / "evaluations"
    if not enabled:
        for argument in config.args:
            target = (config.invocation_params.dir / argument.split("::", 1)[0]).resolve()
            if target.is_relative_to(directory.resolve()):
                raise pytest.UsageError("LLM evaluations require the explicit --run-llm-evals option.")


def pytest_ignore_collect(collection_path: Path, config: pytest.Config) -> bool | None:
    directory = config.rootpath / "tests" / "evaluations"
    if not config.getoption("--run-llm-evals") and collection_path.resolve().is_relative_to(directory.resolve()):
        return True
    return None


@pytest.fixture(autouse=True)
def isolated_settings(monkeypatch: pytest.MonkeyPatch) -> Generator[None, None, None]:
    for settings_type in (ProjectSettings, AzureSettings):
        config = settings_type.model_config.copy()
        config["env_file"] = None
        monkeypatch.setattr(settings_type, "model_config", config)
    template = Path(__file__).resolve().parents[1] / ".env.template"
    for line in template.read_text(encoding="utf-8").splitlines():
        if line.strip() and not line.lstrip().startswith("#"):
            monkeypatch.delenv(line.split("=", 1)[0].strip(), raising=False)
    get_project_settings.cache_clear()
    get_azure_settings.cache_clear()
    try:
        yield
    finally:
        get_project_settings.cache_clear()
        get_azure_settings.cache_clear()


@pytest.fixture
def duckdb_file(tmp_path: Path) -> Path:
    path = tmp_path / "tasks.duckdb"
    with duckdb.connect(str(path)) as connection:
        connection.execute(
            "CREATE TABLE main.fct_tasks (task_id VARCHAR, task_title VARCHAR, "
            "task_description VARCHAR, status VARCHAR, is_completed BOOLEAN)"
        )
    return path

import os

from template_azure_python.settings.project import TaskRepositoryBackend


def functions_environment(repository: TaskRepositoryBackend) -> dict[str, str]:
    return {**os.environ, "TASK_REPOSITORY": repository.value}

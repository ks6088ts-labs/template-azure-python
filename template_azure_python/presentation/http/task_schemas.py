from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from template_azure_python.domain import Task, TaskStatus


class CreateTaskRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=2000)


class UpdateTaskRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=2000)
    status: TaskStatus


class TaskResponse(BaseModel):
    id: UUID
    title: str
    description: str
    status: TaskStatus

    @classmethod
    def from_domain(cls, task: Task) -> "TaskResponse":
        return cls(
            id=task.id,
            title=task.title,
            description=task.description,
            status=task.status,
        )


class ErrorResponse(BaseModel):
    detail: str

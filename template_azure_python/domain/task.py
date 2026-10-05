from dataclasses import dataclass, replace
from enum import Enum
from typing import NewType
from uuid import UUID, uuid4

TaskId = NewType("TaskId", UUID)


class TaskStatus(str, Enum):
    TODO = "todo"
    IN_PROGRESS = "in_progress"
    DONE = "done"


class InvalidTaskError(ValueError):
    pass


def _validated_title(value: str) -> str:
    title = value.strip()
    if not title:
        raise InvalidTaskError("Task title must not be empty")
    if len(title) > 200:
        raise InvalidTaskError("Task title must be at most 200 characters")
    return title


def _validated_description(value: str) -> str:
    description = value.strip()
    if len(description) > 2000:
        raise InvalidTaskError("Task description must be at most 2000 characters")
    return description


@dataclass(frozen=True, slots=True)
class Task:
    id: TaskId
    title: str
    description: str
    status: TaskStatus

    def __post_init__(self) -> None:
        object.__setattr__(self, "title", _validated_title(self.title))
        object.__setattr__(self, "description", _validated_description(self.description))

    @classmethod
    def create(cls, title: str, description: str = "") -> "Task":
        return cls(
            id=TaskId(uuid4()),
            title=title,
            description=description,
            status=TaskStatus.TODO,
        )

    def update(self, *, title: str, description: str, status: TaskStatus) -> "Task":
        return replace(self, title=title, description=description, status=status)

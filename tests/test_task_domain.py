from uuid import UUID

import pytest

from template_azure_python.domain import InvalidTaskError, Task, TaskId, TaskStatus


def test_task_create_normalizes_values():
    task = Task.create(title="  Write tests  ", description="  Cover the domain  ")

    assert task.title == "Write tests"
    assert task.description == "Cover the domain"
    assert task.status is TaskStatus.TODO


@pytest.mark.parametrize(
    ("title", "description", "message"),
    [
        (" ", "", "must not be empty"),
        ("a" * 201, "", "at most 200"),
        ("Valid", "a" * 2001, "at most 2000"),
    ],
)
def test_task_rejects_invalid_values(title: str, description: str, message: str):
    with pytest.raises(InvalidTaskError, match=message):
        Task.create(title=title, description=description)


def test_task_update_returns_new_entity():
    task = Task(
        id=TaskId(UUID("00000000-0000-0000-0000-000000000001")),
        title="Original",
        description="",
        status=TaskStatus.TODO,
    )

    updated = task.update(title="Updated", description="Done", status=TaskStatus.DONE)

    assert updated is not task
    assert updated.id == task.id
    assert updated.title == "Updated"
    assert updated.status is TaskStatus.DONE
    assert task.status is TaskStatus.TODO

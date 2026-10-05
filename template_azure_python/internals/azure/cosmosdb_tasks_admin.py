import json
import re
import subprocess
from dataclasses import dataclass

from template_azure_python.internals.azure._common import (
    InputError,
    OperationError,
    required_value,
    validate_cosmos_resource_name,
    validate_guid,
    validate_name,
    validate_resource_group,
)
from template_azure_python.settings import get_azure_settings

AZ_TIMEOUT_SECONDS = 300
PARTITION_KEY_PATH = "/id"


@dataclass(frozen=True)
class TaskContainerTarget:
    subscription: str
    resource_group: str
    account: str
    database: str
    container: str

    @property
    def resource_id(self) -> str:
        return (
            f"/subscriptions/{self.subscription}/resourceGroups/{self.resource_group}"
            f"/providers/Microsoft.DocumentDB/databaseAccounts/{self.account}"
            f"/sqlDatabases/{self.database}/containers/{self.container}"
        )

    def identity(self) -> dict[str, object]:
        return {
            "subscription": self.subscription,
            "resource_group": self.resource_group,
            "account": self.account,
            "database": self.database,
            "container": self.container,
        }


def resolve_target(
    subscription: str | None,
    resource_group: str | None,
    account_name: str | None,
    database: str | None,
    container: str | None,
) -> TaskContainerTarget:
    settings = get_azure_settings()
    subscription_id = required_value(subscription, settings.resource.subscription_id, "--subscription")
    try:
        validate_guid(subscription_id)
    except InputError:
        raise InputError("must be a subscription UUID", "--subscription") from None
    group = required_value(resource_group, settings.resource.resource_group, "--resource-group")
    validate_name(group, "--resource-group")
    validate_resource_group(group)
    account = required_value(account_name, settings.cosmos_db.account_name, "--account-name")
    if re.fullmatch(r"[a-z0-9][a-z0-9-]{1,42}[a-z0-9]", account) is None:
        raise InputError(
            "must be a Cosmos DB account name (3-44 lowercase letters, digits or hyphens)", "--account-name"
        )
    return TaskContainerTarget(
        subscription=subscription_id,
        resource_group=group,
        account=account,
        database=validate_cosmos_resource_name(
            required_value(database, settings.cosmos_db.database, "--database"), "--database"
        ),
        container=validate_cosmos_resource_name(
            required_value(container, settings.cosmos_db.task_container, "--container"), "--container"
        ),
    )


def _run(target: TaskContainerTarget, resource: str, operation: str, *options: str, json_output: bool = True) -> object:
    arguments = [
        "az",
        "cosmosdb",
        "sql",
        resource,
        operation,
        "--subscription",
        target.subscription,
        "--resource-group",
        target.resource_group,
        "--account-name",
        target.account,
        "--name",
        target.database if resource == "database" else target.container,
    ]
    if resource == "container":
        arguments.extend(["--database-name", target.database])
    arguments.extend([*options, "--output", "json", "--only-show-errors"])
    try:
        result = subprocess.run(
            arguments, check=False, shell=False, capture_output=True, text=True, timeout=AZ_TIMEOUT_SECONDS
        )
    except FileNotFoundError:
        raise OperationError(
            "Azure CLI (az) not found. Install Azure CLI and sign in before managing Task containers."
        ) from None
    except subprocess.TimeoutExpired:
        raise OperationError(
            f"Azure CLI {resource} {operation} timed out; verify resource state before retrying."
        ) from None
    if result.returncode != 0:
        raise OperationError(
            f"Azure CLI {resource} {operation} failed (exit {result.returncode}). "
            "Check az login, management-plane RBAC and the resource settings."
        )
    if not json_output:
        return None
    try:
        value: object = json.loads(result.stdout)
    except json.JSONDecodeError:
        raise OperationError(f"Azure CLI {resource} {operation} returned invalid JSON.") from None
    return value


def _exists(target: TaskContainerTarget, resource: str) -> bool:
    value = _run(target, resource, "exists")
    if not isinstance(value, bool):
        raise OperationError(f"Azure CLI {resource} exists did not return a JSON boolean.")
    return value


def show_container(target: TaskContainerTarget) -> dict[str, object]:
    value = _run(target, "container", "show")
    if not isinstance(value, dict) or not isinstance(value.get("id"), str):
        raise OperationError("Azure CLI container show returned invalid resource metadata.")
    resource = value.get("resource")
    if not isinstance(resource, dict):
        raise OperationError("Azure CLI container show returned invalid resource metadata.")
    partition = resource.get("partitionKey")
    paths = partition.get("paths") if isinstance(partition, dict) else None
    if not isinstance(paths, list) or not paths or not all(isinstance(path, str) for path in paths):
        raise OperationError("Azure CLI container show returned invalid partition metadata.")
    output = {**target.identity(), "id": value["id"], "partition_key": paths}
    state = value.get("provisioningState")
    if state is not None:
        if not isinstance(state, str):
            raise OperationError("Azure CLI container show returned invalid provisioning state.")
        output["provisioning_state"] = state
    return output


def create_container(target: TaskContainerTarget, throughput: int | None = None) -> dict[str, object]:
    if throughput is not None and throughput < 400:
        raise InputError("must be at least 400 RU/s", "--throughput")
    database_created = False
    container_created = False
    try:
        if not _exists(target, "database"):
            value = _run(target, "database", "create")
            if not isinstance(value, dict) or not isinstance(value.get("id"), str):
                raise OperationError("Azure CLI database create returned invalid resource metadata.")
            database_created = True
        if not _exists(target, "container"):
            options = ["--partition-key-path", PARTITION_KEY_PATH]
            if throughput is not None:
                options.extend(["--throughput", str(throughput)])
            _run(target, "container", "create", *options)
            container_created = True
        metadata = show_container(target)
    except OperationError as error:
        progress = "Database was created; it has not been rolled back. " if database_created else ""
        raise OperationError(f"{progress}{error} Verify database/container state before retrying.") from None
    if metadata["partition_key"] != [PARTITION_KEY_PATH]:
        raise InputError("Task container must use /id; existing resources will not be changed.", "--container")
    return {**metadata, "database_created": database_created, "container_created": container_created}


def delete_container(target: TaskContainerTarget) -> dict[str, object]:
    if not _exists(target, "container"):
        raise OperationError("Task container does not exist; no resources were deleted.")
    if show_container(target)["partition_key"] != [PARTITION_KEY_PATH]:
        raise InputError("Refusing to delete a container without the Task /id partition key.", "--container")
    _run(target, "container", "delete", "--yes", json_output=False)
    if _exists(target, "container"):
        raise OperationError("Task container still exists after the deletion command.")
    return {**target.identity(), "deleted": True}

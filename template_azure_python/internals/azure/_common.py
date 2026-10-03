import json
import re
from collections.abc import AsyncGenerator, Callable, Generator
from contextlib import asynccontextmanager, closing, contextmanager
from typing import Protocol, TypeVar
from urllib.parse import urlparse

from azure.core.exceptions import AzureError
from azure.identity import DefaultAzureCredential
from azure.identity.aio import DefaultAzureCredential as AsyncDefaultAzureCredential
from azure.monitor.query import LogsQueryPartialResult, LogsQueryResult, LogsQueryStatus


class InputError(ValueError):
    def __init__(self, message: str, option: str | None = None) -> None:
        super().__init__(message)
        self.option = option


class OperationError(RuntimeError):
    pass


class MissingSetting(InputError):
    pass


def required_value(value: str | None, setting: str | None, option: str) -> str:
    resolved = setting if value is None else value
    if resolved is None:
        raise MissingSetting(f"Missing option '{option}'.", option)
    return resolved


class _Closable(Protocol):
    def close(self) -> None: ...


class _AsyncClosable(Protocol):
    async def close(self) -> None: ...


Client = TypeVar("Client", bound=_Closable)
AsyncClient = TypeVar("AsyncClient", bound=_AsyncClosable)
_DNS_LABEL = re.compile(r"[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?")
_GUID = re.compile(r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}")
_SEGMENT = re.compile(r"[a-zA-Z0-9_().-]+")
_ERROR_CODE = re.compile(r"[a-zA-Z][a-zA-Z0-9_.-]{0,127}")


def _is_hostname(value: str) -> bool:
    labels = value.split(".")
    return len(value) <= 253 and len(labels) >= 2 and all(_DNS_LABEL.fullmatch(label) for label in labels)


def validate_endpoint(value: str, *, allow_path: bool = False) -> str:
    try:
        parsed = urlparse(value)
        valid = (
            value == value.strip()
            and not any(character.isspace() or ord(character) < 32 or ord(character) == 127 for character in value)
            and parsed.scheme == "https"
            and parsed.hostname is not None
            and _is_hostname(parsed.hostname)
            and parsed.username is None
            and parsed.password is None
            and parsed.port in (None, 443)
            and (allow_path or parsed.path in ("", "/"))
            and "?" not in value
            and "#" not in value
            and "\\" not in value
        )
    except ValueError:
        valid = False
    if not valid:
        raise InputError(
            "must be an HTTPS endpoint without credentials, query, fragment, or a non-HTTPS port",
            "--endpoint",
        )
    return value


def validate_namespace(value: str) -> str:
    if not _is_hostname(value):
        raise InputError(
            "must be a fully-qualified namespace hostname, without a scheme, path, port, or credentials",
            "--fully-qualified-namespace",
        )
    return value


def validate_name(value: str, option: str) -> str:
    if not value.strip():
        raise InputError("must not be empty or whitespace", option)
    return value


def validate_json_object(value: str) -> dict[str, object]:
    def reject_constant(constant: str) -> None:
        raise ValueError(f"{constant} is not a JSON value")

    try:
        result = json.loads(value, parse_constant=reject_constant)
        json.dumps(result, allow_nan=False)
    except (ValueError, RecursionError) as exc:
        raise InputError("must be a valid JSON object", "--data") from exc
    if not isinstance(result, dict):
        raise InputError("must be a JSON object", "--data")
    return result


def validate_guid(value: str) -> str:
    if not isinstance(value, str) or not _GUID.fullmatch(value):
        raise InputError("must be a dashed UUID")
    return value


def validate_arm_id(value: str, provider: str, resource_type: str) -> tuple[str, str, str]:
    message = "must be an absolute ARM resource ID for the required resource type"
    if not isinstance(value, str):
        raise InputError(message)
    parts = value.split("/")
    if (
        len(parts) != 9
        or parts[0] != ""
        or parts[1].lower() != "subscriptions"
        or not _GUID.fullmatch(parts[2])
        or parts[3].lower() != "resourcegroups"
        or parts[5].lower() != "providers"
        or parts[6].lower() != provider.lower()
        or parts[7].lower() != resource_type.lower()
        or any(
            not _SEGMENT.fullmatch(part) or part in (".", "..") or part.endswith(".") for part in (parts[4], parts[8])
        )
    ):
        raise InputError(message)
    return parts[2], parts[4], parts[8]


def validate_resource_group(value: str | None) -> str | None:
    if value is not None and (re.fullmatch(r"[A-Za-z0-9_().-]{1,90}", value) is None or value.endswith(".")):
        raise InputError("must be a valid resource group name", "--resource-group")
    return value


@contextmanager
def azure_errors(message: str, *, include_details: bool = False) -> Generator[None, None, None]:
    try:
        yield
    except AzureError as exc:
        raise OperationError(f"{message}: {exc}" if include_details else message) from exc


@contextmanager
def managed_client(service: str, factory: Callable[[DefaultAzureCredential], Client]) -> Generator[Client, None, None]:
    with azure_errors(f"{service} operation failed", include_details=True):
        with closing(DefaultAzureCredential()) as credential:
            with closing(factory(credential)) as client:
                yield client


@asynccontextmanager
async def async_managed_client(
    service: str, factory: Callable[[AsyncDefaultAzureCredential], AsyncClient]
) -> AsyncGenerator[AsyncClient, None]:
    with azure_errors(f"{service} operation failed", include_details=True):
        credential = AsyncDefaultAzureCredential()
        try:
            client = factory(credential)
            try:
                yield client
            finally:
                await client.close()
        finally:
            await credential.close()


def format_logs_result(result: LogsQueryResult | LogsQueryPartialResult) -> dict[str, object]:
    partial = result.status == LogsQueryStatus.PARTIAL
    tables = result.partial_data if isinstance(result, LogsQueryPartialResult) else result.tables
    output: dict[str, object] = {
        "tables": [
            {
                "name": table.name,
                "columns": [
                    {"name": name, "type": column_type} for name, column_type in zip(table.columns, table.columns_types)
                ],
                "rows": [list(row) for row in table.rows],
            }
            for table in tables
        ]
    }
    if partial:
        error = result.partial_error if isinstance(result, LogsQueryPartialResult) else None
        code = getattr(error, "code", None)
        output["error"] = {
            "code": code if isinstance(code, str) and _ERROR_CODE.fullmatch(code) else "PartialError",
            "message": "Azure Logs query returned partial results.",
        }
    return output

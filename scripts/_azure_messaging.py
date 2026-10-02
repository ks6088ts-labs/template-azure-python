"""Shared validation, resource lifetime, and output for messaging quickstarts."""

import json
import re
import sys
from collections.abc import AsyncGenerator, Callable, Generator
from contextlib import asynccontextmanager, closing, contextmanager
from datetime import date, datetime
from typing import Protocol, TypeVar
from urllib.parse import urlparse
from uuid import UUID

import typer
from azure.core.exceptions import AzureError
from azure.identity import DefaultAzureCredential
from azure.identity.aio import DefaultAzureCredential as AsyncDefaultAzureCredential


class _Closable(Protocol):
    def close(self) -> None: ...


class _AsyncClosable(Protocol):
    async def close(self) -> None: ...


Client = TypeVar("Client", bound=_Closable)
AsyncClient = TypeVar("AsyncClient", bound=_AsyncClosable)
_DNS_LABEL = re.compile(r"[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?")


def _is_hostname(value: str) -> bool:
    labels = value.split(".")
    return len(value) <= 253 and len(labels) >= 2 and all(_DNS_LABEL.fullmatch(label) for label in labels)


def validate_endpoint(value: str, *, allow_path: bool = False) -> str:
    """Reject non-HTTPS endpoints and embedded credentials, including SAS queries."""
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
        raise typer.BadParameter(
            "must be an HTTPS endpoint without credentials, query, fragment, or a non-HTTPS port",
            param_hint="--endpoint",
        )
    return value


def validate_namespace(value: str) -> str:
    if not _is_hostname(value):
        raise typer.BadParameter(
            "must be a fully-qualified namespace hostname, without a scheme, path, port, or credentials",
            param_hint="--fully-qualified-namespace",
        )
    return value


def validate_name(value: str, option: str) -> str:
    if not value.strip():
        raise typer.BadParameter("must not be empty or whitespace", param_hint=option)
    return value


def validate_json_object(value: str) -> dict:
    def reject_constant(constant: str) -> None:
        raise ValueError(f"{constant} is not a JSON value")

    try:
        result = json.loads(value, parse_constant=reject_constant)
        json.dumps(result, allow_nan=False)
    except (ValueError, RecursionError) as exc:
        raise typer.BadParameter("must be a valid JSON object", param_hint="--data") from exc
    if not isinstance(result, dict):
        raise typer.BadParameter("must be a JSON object", param_hint="--data")
    return result


@contextmanager
def report_azure_errors(service: str) -> Generator[None, None, None]:
    try:
        yield
    except AzureError as exc:
        typer.echo(f"Error: {service} operation failed: {exc}", err=True)
        raise typer.Exit(code=1) from exc


@contextmanager
def managed_client(
    service: str,
    factory: Callable[[DefaultAzureCredential], Client],
) -> Generator[Client, None, None]:
    with report_azure_errors(service):
        with closing(DefaultAzureCredential()) as credential:
            with closing(factory(credential)) as client:
                yield client


@asynccontextmanager
async def async_managed_client(
    service: str,
    factory: Callable[[AsyncDefaultAzureCredential], AsyncClient],
) -> AsyncGenerator[AsyncClient, None]:
    with report_azure_errors(service):
        credential = AsyncDefaultAzureCredential()
        try:
            client = factory(credential)
            try:
                yield client
            finally:
                await client.close()
        finally:
            await credential.close()


def _json_default(value: object) -> str:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    raise TypeError(f"Cannot serialize {type(value).__name__} as JSON")


def print_json(value: object) -> None:
    """Emit one complete JSON record per line for streaming and automation."""
    typer.echo(json.dumps(value, default=_json_default, ensure_ascii=False, allow_nan=False))


def confirm_delete(resource: str, yes: bool) -> bool:
    if yes:
        return True
    if not sys.stdin.isatty():
        raise typer.BadParameter("non-interactive queue deletion requires --yes", param_hint="--yes")
    return typer.confirm(f"Delete queue {resource!r}? This cannot be undone.", default=False, err=True)

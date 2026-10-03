import json
import sys
from collections.abc import Generator
from contextlib import contextmanager
from datetime import date, datetime
from uuid import UUID

import typer

from template_azure_python.internals.azure._common import InputError, MissingSetting, OperationError


class _MissingOption(typer.BadParameter):
    def format_message(self) -> str:
        return self.message


@contextmanager
def cli_errors(*, json_error: bool = False) -> Generator[None, None, None]:
    try:
        yield
    except MissingSetting as exc:
        raise _MissingOption(str(exc), param_hint=exc.option) from exc
    except InputError as exc:
        raise typer.BadParameter(str(exc), param_hint=exc.option) from exc
    except OperationError as exc:
        if json_error:
            print_json({"error": str(exc)})
        else:
            typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1) from exc


def _json_default(value: object) -> str:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    raise TypeError(f"Cannot serialize {type(value).__name__} as JSON")


def print_json(value: object, *, indent: int | None = None) -> None:
    typer.echo(json.dumps(value, default=_json_default, ensure_ascii=False, allow_nan=False, indent=indent))


def print_logs(output: dict[str, object]) -> None:
    print_json(output)
    if "error" in output:
        raise typer.Exit(1)


def confirm_delete(resource: str, yes: bool) -> bool:
    if yes:
        return True
    if not sys.stdin.isatty():
        raise typer.BadParameter("non-interactive queue deletion requires --yes", param_hint="--yes")
    return typer.confirm(f"Delete queue {resource!r}? This cannot be undone.", default=False, err=True)

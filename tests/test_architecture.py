import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "template_azure_python"
SCRIPTS = ROOT / "scripts"


def _imports(tree: ast.AST) -> list[str]:
    modules = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            modules.append(node.module)
    return modules


@pytest.mark.parametrize("path", sorted(SCRIPTS.glob("*.py")), ids=lambda path: path.name)
def test_cli_does_not_import_sdks(path: Path):
    modules = _imports(ast.parse(path.read_text(encoding="utf-8")))
    assert not [module for module in modules if module.split(".")[0] in {"azure", "openai", "opentelemetry"}]


@pytest.mark.parametrize(
    "path",
    sorted(
        path for path in [*PACKAGE.rglob("*.py"), *SCRIPTS.glob("*.py")] if PACKAGE / "settings" not in path.parents
    ),
    ids=lambda path: str(path.relative_to(ROOT)),
)
def test_environment_access_is_only_in_settings(path: Path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    assert not [module for module in _imports(tree) if module.split(".")[0] in {"dotenv", "pydantic_settings"}]
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute):
            assert node.attr not in {"environ", "getenv", "putenv", "unsetenv"}
        elif isinstance(node, ast.ImportFrom) and node.module == "os":
            assert not {"environ", "getenv", "putenv", "unsetenv"} & {alias.name for alias in node.names}
        elif isinstance(node, ast.keyword):
            assert node.arg != "envvar"


@pytest.mark.parametrize("path", sorted((PACKAGE / "internals" / "azure").glob("*.py")), ids=lambda path: path.name)
def test_azure_internals_are_not_cli_code(path: Path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    assert not [module for module in _imports(tree) if module.split(".")[0] in {"typer", "scripts"}]
    assert not [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "print"
    ]

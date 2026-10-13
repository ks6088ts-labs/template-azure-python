import json
import tomllib
from pathlib import Path
from unittest.mock import Mock

import pytest

from scripts.init_template import initialize
from scripts.init_template import main as initialize_main
from scripts.smoke_test import check_health, main

ROOT = Path(__file__).resolve().parents[1]


def test_runtime_dependencies_are_separate_from_integrations():
    metadata = tomllib.loads((ROOT / "pyproject.toml").read_text())
    project = metadata["project"]
    assert project["requires-python"] == ">=3.13"
    assert (ROOT / ".python-version").read_text().strip() == "3.14"
    dependencies = project["dependencies"]
    assert any(dependency.startswith("fastapi>=") for dependency in dependencies)
    assert not any(dependency.startswith("fastapi[") for dependency in dependencies)
    assert any(dependency.startswith("uvicorn>=") for dependency in dependencies)
    assert any(dependency.startswith("azure-monitor-opentelemetry") for dependency in dependencies)
    assert not any(
        dependency.startswith(("duckdb", "azure-cosmos", "azure-functions", "typer")) for dependency in dependencies
    )
    assert set(project["optional-dependencies"]) == {"cosmos", "duckdb", "storage", "functions", "samples"}
    assert metadata["build-system"]["build-backend"] == "uv_build"
    assert metadata["tool"]["uv"]["build-backend"]["module-root"] == "."
    assert all("==" in requirement for requirement in metadata["build-system"]["requires"])
    version = metadata["tool"]["uv"]["required-version"].removeprefix("==")
    assert metadata["build-system"]["requires"] == [f"uv_build=={version}"]
    assert "pythonpath" not in metadata["tool"]["pytest"]["ini_options"]
    assert "--import-mode=importlib" in metadata["tool"]["pytest"]["ini_options"]["addopts"]
    assert metadata["tool"]["coverage"]["run"]["branch"] is True
    assert metadata["tool"]["coverage"]["report"]["fail_under"] == 85
    assert metadata["tool"]["uv"]["exclude-newer"] == "7 days"
    assert metadata["tool"]["uv"]["exclude-newer-package"] == {"fastapi": "3 days", "uv-build": "3 days"}
    assert any(
        dependency.startswith("mkdocs>=") and "<2" in dependency for dependency in metadata["dependency-groups"]["docs"]
    )


def test_release_versions_agree():
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]
    manifest = json.loads((ROOT / ".release-please-manifest.json").read_text())
    assert project["version"] == (ROOT / "version.txt").read_text().strip() == manifest["."]
    config = json.loads((ROOT / "release-please-config.json").read_text())
    assert config["packages"]["."]["package-name"] == project["name"]
    assert config["packages"]["."]["release-type"] == "simple"
    assert config["packages"]["."]["version-file"] == "version.txt"


def test_production_container_is_non_root_and_allowlisted():
    dockerfile = (ROOT / "Dockerfile").read_text()
    assert "USER 10001:10001" in dockerfile
    assert "COPY . ." not in dockerfile
    assert "--no-hashes" not in dockerfile
    assert "uv sync --locked --no-default-groups --no-editable" in dockerfile
    assert '"template_azure_python"' in dockerfile
    assert ".venv /app/.venv" in dockerfile
    assert (ROOT / ".dockerignore").read_text().splitlines()[0] == "**"
    compose = (ROOT / "compose.yml").read_text()
    assert "read_only: true" in compose
    assert "127.0.0.1:8000:8000" in compose
    assert "/var/run/docker.sock" not in (ROOT / "Makefile").read_text()
    assert "ghcr.io/astral-sh/uv@sha256:" in dockerfile
    assert "slim-trixie@sha256:" in dockerfile
    assert 'APP_VERSION="${GIT_TAG}"' in dockerfile
    assert "/usr/local/lib/python3.14/ensurepip" in dockerfile


def test_developer_checks_have_one_required_type_checker():
    makefile = (ROOT / "Makefile").read_text()
    lint_python = makefile.split("lint-python:", 1)[1].split("ACTIONLINT_VERSION", 1)[0]
    assert "mypy" in lint_python
    assert "ty check" not in lint_python
    assert "pyrefly check" not in lint_python
    assert "mkdocs build --strict" in makefile
    assert "pytest -q" in makefile
    assert "uv" in makefile and "--all-extras" in makefile
    assert "repo: builtin" in (ROOT / ".pre-commit-config.yaml").read_text()


@pytest.fixture
def metadata_root(tmp_path):
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "template-azure-python"\nversion = "0.0.1"\ndescription = "Original"\n'
        '\n[tool.example]\nname = "do-not-change"\n'
    )
    (tmp_path / "LICENSE").write_text("Copyright original author\n")
    (tmp_path / ".devcontainer").mkdir()
    (tmp_path / ".devcontainer/devcontainer.json").write_text('{"name": "template-azure-python"}\n')
    (tmp_path / "release-please-config.json").write_text(
        '{"packages": {".": {"release-type": "python", "package-name": "template-azure-python"}}}\n'
    )
    (tmp_path / "template_azure_python").mkdir()
    (tmp_path / "template_azure_python/__init__.py").write_text('NAME = "template_azure_python"\n')
    return tmp_path


def test_initializer_defaults_to_dry_run(metadata_root, capsys):
    paths = initialize(metadata_root, "my-service", description="A new description")
    assert len(paths) == 3
    assert 'name = "my-service"' in capsys.readouterr().out
    assert tomllib.loads((metadata_root / "pyproject.toml").read_text())["project"]["name"] == "template-azure-python"


def test_initializer_changes_metadata_not_imports_or_attribution(metadata_root):
    initialize(metadata_root, "my-service", description='A "quoted" description\nwith a newline', dry_run=False)
    metadata = tomllib.loads((metadata_root / "pyproject.toml").read_text())
    assert metadata["project"]["name"] == "my-service"
    assert metadata["project"]["description"] == 'A "quoted" description\nwith a newline'
    assert metadata["tool"]["example"]["name"] == "do-not-change"
    assert (metadata_root / "LICENSE").read_text() == "Copyright original author\n"
    assert (metadata_root / "template_azure_python/__init__.py").read_text() == 'NAME = "template_azure_python"\n'
    assert json.loads((metadata_root / ".devcontainer/devcontainer.json").read_text())["name"] == "my-service"
    assert initialize(metadata_root, "my-service", dry_run=False) == []


@pytest.mark.parametrize("name", ["../escape", "Uppercase", "my_service", "-name", "name--name", ""])
def test_initializer_rejects_unsafe_names(metadata_root, name):
    with pytest.raises(ValueError, match="Name must"):
        initialize(metadata_root, name, dry_run=False)


def test_initializer_refuses_symlinks(metadata_root):
    path = metadata_root / ".devcontainer/devcontainer.json"
    original = metadata_root / "original.json"
    path.rename(original)
    path.symlink_to(original)
    with pytest.raises(ValueError, match="symlink"):
        initialize(metadata_root, "my-service", dry_run=False)
    assert tomllib.loads((metadata_root / "pyproject.toml").read_text())["project"]["name"] == "template-azure-python"


def test_initializer_does_not_delete_preexisting_staging_file(metadata_root):
    staging = metadata_root / ".pyproject.toml.init-template"
    staging.write_text("Keep this file\n")
    with pytest.raises(FileExistsError):
        initialize(metadata_root, "my-service", dry_run=False)
    assert staging.read_text() == "Keep this file\n"


def _repository_metadata_files(root):
    (root / "mkdocs.yml").write_text(
        "site_name: template-azure-python\n"
        "site_url: https://OWNER.github.io/template-azure-python/\n"
        "repo_url: https://github.com/OWNER/template-azure-python\n"
        "repo_name: OWNER/template-azure-python\n"
        "copyright: Copyright 2023 original author\n"
        "plugins:\n  - i18n\n"
    )
    (root / ".github/ISSUE_TEMPLATE").mkdir(parents=True)
    (root / ".github/CODEOWNERS").write_text("* @OWNER\n/.github/ @OWNER\n")
    (root / ".github/ISSUE_TEMPLATE/config.yml").write_text(
        "contact_links:\n  - url: https://github.com/OWNER/template-azure-python/security/advisories/new\n"
    )
    (root / "README.md").write_text(
        "# template-azure-python\n"
        "[ci](https://github.com/OWNER/template-azure-python/actions/workflows/ci.yaml)\n"
        "[Python](https://github.com/python/cpython)\n"
        "Copyright original author https://github.com/OWNER/template-azure-python\n"
    )
    (root / "Makefile").write_text(
        "DOCKER_REPO_NAME ?= original-owner\nDOCKER_IMAGE_NAME ?= template-azure-python\n"
        "package:\n\tpython -m template_azure_python\n"
    )


def test_initializer_updates_repository_metadata_and_preserves_attribution(metadata_root):
    _repository_metadata_files(metadata_root)
    paths = initialize(metadata_root, owner="my-org", repository="My_Service", dry_run=False)
    assert len(paths) == 8
    assert tomllib.loads((metadata_root / "pyproject.toml").read_text())["project"]["name"] == "my-service"
    mkdocs = (metadata_root / "mkdocs.yml").read_text()
    assert "site_url: https://my-org.github.io/My_Service/" in mkdocs
    assert "repo_name: my-org/My_Service" in mkdocs
    assert "copyright: Copyright 2023 original author" in mkdocs
    assert "plugins:\n  - i18n" in mkdocs
    assert (metadata_root / ".github/CODEOWNERS").read_text() == "* @my-org\n/.github/ @my-org\n"
    assert (
        "https://github.com/my-org/My_Service/security/advisories/new"
        in (metadata_root / ".github/ISSUE_TEMPLATE/config.yml").read_text()
    )
    readme = (metadata_root / "README.md").read_text()
    assert "# my-service\n" in readme
    assert "[ci](https://github.com/my-org/My_Service/actions/workflows/ci.yaml)" in readme
    assert "[Python](https://github.com/python/cpython)" in readme
    assert "Copyright original author https://github.com/OWNER/template-azure-python" in readme
    assert (metadata_root / "LICENSE").read_text() == "Copyright original author\n"
    makefile = (metadata_root / "Makefile").read_text()
    assert "DOCKER_REPO_NAME ?= my-org" in makefile
    assert "DOCKER_IMAGE_NAME ?= my_service" in makefile
    assert "python -m template_azure_python" in makefile
    assert initialize(metadata_root, owner="my-org", repository="My_Service", dry_run=False) == []


def test_initializer_repository_cli_defaults_to_safe_dry_run(metadata_root, capsys):
    _repository_metadata_files(metadata_root)
    assert initialize_main(["--root", str(metadata_root), "--owner", "my-org", "--repository", "my-service"]) == 0
    preview = capsys.readouterr().out
    assert "https://github.com/my-org/my-service/actions/workflows/ci.yaml" in preview
    assert "Would update 8 metadata file(s)" in preview
    assert "* @OWNER" in (metadata_root / ".github/CODEOWNERS").read_text()


@pytest.mark.parametrize(
    ("owner", "repository"),
    [("../escape", "repo"), ("org/team", "repo"), ("org", "../escape"), ("org", "https://github.com/org/repo")],
)
def test_initializer_rejects_unsafe_repository_metadata(metadata_root, owner, repository):
    with pytest.raises(ValueError):
        initialize(metadata_root, owner=owner, repository=repository, dry_run=False)


def test_initializer_refuses_docs_metadata_symlinks_before_writing(metadata_root):
    _repository_metadata_files(metadata_root)
    path = metadata_root / "README.md"
    original = metadata_root / "original-readme"
    path.rename(original)
    path.symlink_to(original)
    with pytest.raises(ValueError, match="symlink"):
        initialize(metadata_root, owner="my-org", repository="my-service", dry_run=False)
    assert "* @OWNER" in (metadata_root / ".github/CODEOWNERS").read_text()


def test_smoke_probe_is_read_only(monkeypatch):
    connection = Mock()
    connection.getresponse.return_value.status = 200
    connection.getresponse.return_value.read.return_value = b'{"status":"ok"}'
    constructor = Mock(return_value=connection)
    monkeypatch.setattr("scripts.smoke_test.http.client.HTTPConnection", constructor)
    check_health("http://127.0.0.1:8000")
    assert [call.args for call in connection.request.call_args_list] == [("GET", "/healthz"), ("GET", "/readyz")]
    assert connection.close.call_count == 2


def test_smoke_probe_rejects_unready_application(monkeypatch):
    connection = Mock()
    connection.getresponse.return_value.status = 503
    monkeypatch.setattr("scripts.smoke_test.http.client.HTTPConnection", Mock(return_value=connection))
    with pytest.raises(RuntimeError, match="503"):
        check_health("http://127.0.0.1:8000")
    connection.close.assert_called_once()


def test_smoke_probe_does_not_require_json_payloads(monkeypatch):
    connection = Mock()
    connection.getresponse.return_value.status = 200
    monkeypatch.setattr("scripts.smoke_test.http.client.HTTPConnection", Mock(return_value=connection))
    check_health("http://127.0.0.1:8000")
    connection.getresponse.return_value.read.assert_not_called()


@pytest.mark.parametrize(
    "origin", ["file:///etc/passwd", "******localhost", "http://localhost/tasks", "https://localhost?token=x"]
)
def test_smoke_probe_rejects_non_origins(origin):
    with pytest.raises(ValueError, match="HTTP"):
        check_health(origin)


@pytest.mark.parametrize("interval_flag", ["--interval", "--delay"])
def test_smoke_command_retries_without_mutation(monkeypatch, capsys, interval_flag):
    probe = Mock(side_effect=[RuntimeError("not ready"), None])
    monkeypatch.setattr("scripts.smoke_test.check_health", probe)
    assert main(["--attempts", "2", interval_flag, "0"]) == 0
    assert probe.call_count == 2
    assert "GET /healthz and /readyz succeeded" in capsys.readouterr().out

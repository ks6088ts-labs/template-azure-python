"""Customize distribution metadata without renaming imports or changing attribution."""

import argparse
import difflib
import json
import re
import sys
import tomllib
from collections.abc import Sequence
from pathlib import Path

METADATA_FILES = (
    "pyproject.toml",
    ".devcontainer/devcontainer.json",
    "release-please-config.json",
    "mkdocs.yml",
    ".github/CODEOWNERS",
    ".github/ISSUE_TEMPLATE/config.yml",
    "README.md",
    "Makefile",
)


def _metadata_path(root: Path, relative: str) -> Path:
    path = root / relative
    if path.is_symlink() or not path.resolve().is_relative_to(root):
        raise ValueError(f"Refusing to modify a metadata symlink: {relative}")
    return path


def _project_metadata(text: str, name: str, description: str | None) -> str:
    match = re.search(r"(?ms)^\[project\]\n(.*?)(?=^\[|\Z)", text)
    if match is None:
        raise ValueError("pyproject.toml is missing its [project] table.")
    section = re.sub(r"(?m)^name\s*=.*$", f"name = {json.dumps(name)}", match.group(1), count=1)
    if description is not None:
        section = re.sub(
            r"(?m)^description\s*=.*$",
            lambda _: f"description = {json.dumps(description)}",
            section,
            count=1,
        )
    result = text[: match.start(1)] + section + text[match.end(1) :]
    tomllib.loads(result)
    return result


def _repository_metadata(
    text: str,
    *,
    name: str,
    owner: str | None,
    repository: str | None,
    previous_owner: str,
    previous_repositories: set[str],
) -> str:
    def github_link(match: re.Match[str]) -> str:
        old_owner, old_repository = match.groups()
        if old_repository not in previous_repositories:
            return match.group()
        return f"https://github.com/{owner or old_owner}/{repository or old_repository}"

    def pages_link(match: re.Match[str]) -> str:
        old_owner, old_repository = match.groups()
        if old_repository not in previous_repositories:
            return match.group()
        return f"https://{owner or old_owner}.github.io/{repository or old_repository}"

    lines: list[str] = []
    for line in text.splitlines(keepends=True):
        if "copyright" in line.lower():
            lines.append(line)
            continue
        line = re.sub(r"https://github\.com/([A-Za-z0-9-]+)/([A-Za-z0-9_.-]+)", github_link, line)
        line = re.sub(r"https://([A-Za-z0-9-]+)\.github\.io/([A-Za-z0-9_.-]+)", pages_link, line)
        if line.startswith("repo_name:"):
            line = f"repo_name: {owner or previous_owner}/{repository or name}\n"
        elif line.startswith("site_name:"):
            line = f"site_name: {name}\n"
        elif line.strip() in {f"# {old_name}" for old_name in previous_repositories}:
            line = f"# {name}\n"
        elif line.startswith("DOCKER_REPO_NAME ?=") and owner is not None:
            line = f"DOCKER_REPO_NAME ?= {owner}\n"
        elif line.startswith("DOCKER_IMAGE_NAME ?=") and repository is not None:
            line = f"DOCKER_IMAGE_NAME ?= {repository.lower()}\n"
        if owner is not None:
            line = re.sub(
                rf"(?<!\w)@(?:OWNER|{re.escape(previous_owner)})(?=[\s/]|$)",
                f"@{owner}",
                line,
            )
        lines.append(line)
    return "".join(lines)


def initialize(
    root: Path,
    name: str | None = None,
    *,
    description: str | None = None,
    owner: str | None = None,
    repository: str | None = None,
    dry_run: bool = True,
) -> list[Path]:
    if owner is not None and re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?", owner) is None:
        raise ValueError("Owner must be a GitHub user or organization name, not a path or team.")
    if repository is not None and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,99}", repository) is None:
        raise ValueError("Repository must be a GitHub repository name, not a URL or path.")
    root = root.resolve()
    if not (root / "pyproject.toml").is_file() or not (root / "LICENSE").is_file():
        raise ValueError("Choose a template root containing pyproject.toml and LICENSE.")
    project = tomllib.loads(_metadata_path(root, "pyproject.toml").read_text(encoding="utf-8"))["project"]
    previous_name = str(project["name"])
    if name is None:
        name = re.sub(r"[-_.]+", "-", repository.lower()).strip("-") if repository else previous_name
    if re.fullmatch(r"[a-z][a-z0-9]*(?:-[a-z0-9]+)*", name) is None:
        raise ValueError("Name must use lowercase letters, digits, and single separating hyphens.")
    previous_owner = "OWNER"
    previous_repositories = {previous_name, "template-azure-python"}
    mkdocs = _metadata_path(root, "mkdocs.yml")
    if mkdocs.exists():
        match = re.search(
            r"""(?m)^repo_url:\s*['"]?https://github\.com/([^/\s'"]+)/([^/\s'"]+)""",
            mkdocs.read_text(encoding="utf-8"),
        )
        if match is not None:
            previous_owner = match.group(1)
            previous_repositories.add(match.group(2))
    plans: list[tuple[Path, str, str]] = []
    for relative in METADATA_FILES:
        path = _metadata_path(root, relative)
        if not path.exists():
            continue
        original = path.read_text(encoding="utf-8")
        if relative == "pyproject.toml":
            updated = _project_metadata(original, name, description)
        elif relative == "release-please-config.json":
            config = json.loads(original)
            config["packages"]["."]["package-name"] = name
            updated = json.dumps(config, indent=2) + "\n"
        elif relative == ".devcontainer/devcontainer.json":
            updated = re.sub(r'("name"\s*:\s*)"[^"]*"', lambda m: m.group(1) + json.dumps(name), original, count=1)
        elif owner is not None or repository is not None:
            updated = _repository_metadata(
                original,
                name=name,
                owner=owner,
                repository=repository,
                previous_owner=previous_owner,
                previous_repositories=previous_repositories,
            )
        else:
            updated = original
        if updated != original:
            plans.append((path, original, updated))
    for path, original, updated in plans:
        relative = str(path.relative_to(root))
        if dry_run:
            sys.stdout.writelines(
                difflib.unified_diff(
                    original.splitlines(keepends=True),
                    updated.splitlines(keepends=True),
                    fromfile=relative,
                    tofile=relative,
                )
            )
        else:
            staging = path.with_name(f".{path.name}.init-template")
            created = False
            try:
                with staging.open("x", encoding="utf-8") as output:
                    created = True
                    output.write(updated)
                staging.replace(path)
            finally:
                if created:
                    staging.unlink(missing_ok=True)
    return [path for path, _, _ in plans]


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--name", help="distribution name (defaults to the normalized repository name)")
    parser.add_argument("--owner", help="GitHub user or organization")
    parser.add_argument("--repository", help="GitHub repository name")
    parser.add_argument("--description")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--apply", action="store_true", help="write metadata changes (default: dry run)")
    mode.add_argument("--dry-run", action="store_true", help="preview metadata changes without writing")
    args = parser.parse_args(argv)
    if args.name is None and args.owner is None and args.repository is None:
        parser.error("provide --name or --owner/--repository metadata")
    try:
        paths = initialize(
            args.root,
            args.name,
            description=args.description,
            owner=args.owner,
            repository=args.repository,
            dry_run=not args.apply,
        )
    except (OSError, ValueError, KeyError) as error:
        parser.exit(1, f"Initialization failed: {error}\n")
    action = "Updated" if args.apply else "Would update"
    print(f"{action} {len(paths)} metadata file(s); package imports and LICENSE stay unchanged.")
    if args.apply and paths:
        print("Run uv lock to synchronize the renamed distribution metadata.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

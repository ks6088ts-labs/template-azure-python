import io
import json

import pytest

from scripts.agent_guardrails import main, rejection_reason


@pytest.mark.parametrize(
    "command",
    [
        "git push --force",
        "git push -f origin main",
        "/usr/bin/git push --force-with-lease",
        "azd down --force",
        "az group delete --name demo",
        "az rest --method DELETE --url https://management.azure.com/resource",
        "rm -rf /",
        "rm -rf '$HOME'",
        "bash -c 'git push --force'",
        "sh -c 'az group delete --name demo'",
    ],
)
def test_common_destructive_commands_are_rejected(command):
    assert rejection_reason(command)


@pytest.mark.parametrize(
    "command",
    [
        "uv run --locked pytest",
        "git status",
        "git diff --check",
        "az bicep build --file infra/main.bicep",
        "rm /tmp/file",
    ],
)
def test_ordinary_development_commands_are_allowed(command):
    assert rejection_reason(command) is None


def test_hook_does_not_repeat_sensitive_arguments(monkeypatch, capsys):
    monkeypatch.setattr(
        "sys.stdin",
        io.StringIO(json.dumps({"toolArgs": {"command": "az group delete --name private-resource"}})),
    )
    assert main() == 0
    output = json.loads(capsys.readouterr().out)
    assert output["permissionDecision"] == "deny"
    assert "private-resource" not in output["permissionDecisionReason"]


def test_malformed_input_is_denied(monkeypatch, capsys):
    monkeypatch.setattr("sys.stdin", io.StringIO("not json"))
    assert main() == 0
    assert json.loads(capsys.readouterr().out)["permissionDecision"] == "deny"

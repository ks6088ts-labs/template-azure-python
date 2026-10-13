import json
import shlex
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_bootstrap_rejects_missing_arguments():
    result = subprocess.run(
        ["bash", str(ROOT / "scripts/bootstrap-azure.sh")],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2
    assert "Usage:" in result.stderr


@pytest.mark.parametrize("environment", ["preview", "production;echo unsafe"])
def test_bootstrap_rejects_invalid_environment(environment):
    result = subprocess.run(
        [
            "bash",
            str(ROOT / "scripts/bootstrap-azure.sh"),
            "owner/repo",
            environment,
            "resource-group",
            "eastus",
            "demo",
            "ghcr.io/owner/repo@sha256:" + "a" * 64,
            "00000000-0000-0000-0000-000000000000",
            "1",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert result.stdout == ""


def test_release_tag_rules_require_explicit_publisher_bypass():
    rules = json.loads((ROOT / ".github/rulesets/release-tags.json").read_text())
    assert rules["bypass_actors"] == []
    assert {rule["type"] for rule in rules["rules"]} == {"creation", "update", "deletion"}


def test_main_rules_gate_codeql_and_merge_queue():
    rules = json.loads((ROOT / ".github/rulesets/main.json").read_text())
    by_type = {rule["type"]: rule for rule in rules["rules"]}
    assert "merge_queue" in by_type
    tool = by_type["code_scanning"]["parameters"]["code_scanning_tools"][0]
    assert tool["tool"] == "CodeQL"
    assert tool["security_alerts_threshold"] == "medium_or_higher"


def test_infrastructure_uses_environment_identity_and_secure_runtime():
    main = (ROOT / "infra/main.bicep").read_text()
    app = (ROOT / "infra/app.bicep").read_text()
    assert "repo:${githubRepository}:environment:${environment}" in main
    assert "DisableLocalAuth: true" in main
    assert "adminUserEnabled: false" in main
    assert "param externalIngress bool = false" in main
    assert "external: externalIngress" in app
    assert "maxReplicas: 1" in app
    assert "excludedPaths: ['/healthz', '/readyz']" in app
    assert "allowInsecure: false" in app
    assert "value: 'easyauth'" in app


def test_bootstrap_opens_ingress_only_after_auth_deployment():
    bootstrap = (ROOT / "scripts/bootstrap-azure.sh").read_text()
    assert bootstrap.index("az deployment group create") < bootstrap.index("az containerapp ingress enable")


def _bootstrap_with_mock_commands(gh_function: str):
    script = shlex.quote(str(ROOT / "scripts/bootstrap-azure.sh"))
    return subprocess.run(
        [
            "bash",
            "-c",
            gh_function
            + "\naz() { echo 'Azure reached'; return 21; }; export -f gh az;\n"
            + f"bash {script} owner/repo staging resource-group eastus demo "
            + "ghcr.io/owner/repo@sha256:"
            + "a" * 64
            + " 00000000-0000-0000-0000-000000000000 1",
        ],
        capture_output=True,
        text=True,
        check=False,
    )


def test_bootstrap_rejects_unsafe_existing_policies_before_mutation():
    result = _bootstrap_with_mock_commands(
        """gh() {
  case "$*" in
    *"--method PUT"*) echo 'Protection changed'; return 99 ;;
    *deployment-branch-policies*) echo '{"branch_policies":[{"name":"release/*","type":"branch"}]}' ;;
    *) echo '{"protection_rules":[]}' ;;
  esac
}"""
    )
    assert result.returncode == 1
    assert "non-main" in result.stderr
    assert "Protection changed" not in result.stdout
    assert "Azure reached" not in result.stdout


def test_bootstrap_preserves_existing_reviewers_and_wait_timer():
    result = _bootstrap_with_mock_commands(
        """gh() {
  case "$*" in
    *"--method PUT"*)
      jq -e '.reviewers == [{"type":"User","id":42}] and .wait_timer == 15
             and .prevent_self_review == true and .can_admins_bypass == false' "$6" >/dev/null ;;
    *deployment-branch-policies*) echo '{"branch_policies":[{"name":"main","type":"branch"}]}' ;;
    *) echo '{"protection_rules":[{"type":"required_reviewers","reviewers":[{"type":"User","reviewer":{"id":42}}]},
              {"type":"wait_timer","wait_timer":15}]}' ;;
  esac
}"""
    )
    assert result.returncode == 21, result.stderr
    assert "Azure reached" in result.stdout


def test_docs_do_not_collect_author_analytics():
    config = (ROOT / "mkdocs.yml").read_text()
    assert "analytics:" not in config
    assert "linkedin.com/in/" not in config
    assert "x.com/" not in config

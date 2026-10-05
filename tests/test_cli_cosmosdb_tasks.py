import json
import subprocess
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from scripts.cli_cosmosdb import app
from template_azure_python.internals.azure import cosmosdb_tasks_admin as admin

SUBSCRIPTION = "00000000-0000-0000-0000-000000000001"
TARGET = admin.TaskContainerTarget(SUBSCRIPTION, "test-group", "test-account", "cosmicworks", "tasks")
METADATA = {"id": TARGET.resource_id, "resource": {"partitionKey": {"paths": ["/id"]}}}
OPTIONS = ["--subscription", SUBSCRIPTION, "--resource-group", "test-group", "--account-name", "test-account"]


@pytest.fixture
def run():
    with patch.object(admin.subprocess, "run") as mocked:
        yield mocked


def results(run, *values):
    run.side_effect = [subprocess.CompletedProcess([], 0, json.dumps(value), "") for value in values]


def invoke(command, *options):
    return CliRunner().invoke(app, ["tasks", command, *OPTIONS, *options])


@pytest.mark.parametrize("throughput", [None, 500])
def test_create_missing_resources_and_validate(throughput, run):
    results(run, False, {"id": "database-id"}, False, METADATA, METADATA)
    response = invoke("create-container", *(["--throughput", str(throughput)] if throughput else []))
    assert response.exit_code == 0, response.output
    output = json.loads(response.output)
    assert output["database_created"] is output["container_created"] is True
    assert output["partition_key"] == ["/id"]
    calls = [call.args[0] for call in run.call_args_list]
    assert [(call[3], call[4]) for call in calls] == [
        ("database", "exists"),
        ("database", "create"),
        ("container", "exists"),
        ("container", "create"),
        ("container", "show"),
    ]
    for call in run.call_args_list:
        assert call.kwargs == {
            "check": False,
            "shell": False,
            "capture_output": True,
            "text": True,
            "timeout": admin.AZ_TIMEOUT_SECONDS,
        }
        assert call.args[0][:3] == ["az", "cosmosdb", "sql"]
        for key, value in [
            ("--subscription", SUBSCRIPTION),
            ("--resource-group", "test-group"),
            ("--account-name", "test-account"),
            ("--output", "json"),
        ]:
            assert call.args[0][call.args[0].index(key) + 1] == value
    create = calls[3]
    assert create[create.index("--name") + 1] == "tasks"
    assert create[create.index("--database-name") + 1] == "cosmicworks"
    assert create[create.index("--partition-key-path") + 1] == "/id"
    if throughput:
        assert create[create.index("--throughput") + 1] == str(throughput)
    else:
        assert not any("--throughput" in call for call in calls)


def test_create_is_idempotent_and_does_not_change_existing_throughput(run):
    results(run, True, True, METADATA)
    response = invoke("create-container", "--throughput", "500")
    assert response.exit_code == 0, response.output
    output = json.loads(response.output)
    assert output["database_created"] is output["container_created"] is False
    assert not any("create" in call.args[0] or "--throughput" in call.args[0] for call in run.call_args_list)


def test_existing_incompatible_container_is_not_recreated(run):
    results(run, True, True, {"id": TARGET.resource_id, "resource": {"partitionKey": {"paths": ["/category"]}}})
    response = invoke("create-container")
    assert response.exit_code == 2
    assert "/id" in response.output
    assert not any("create" in call.args[0] or "delete" in call.args[0] for call in run.call_args_list)


def test_show_has_no_creation_and_returns_safe_metadata(run):
    results(run, {**METADATA, "provisioningState": "Succeeded", "unrelated": "not-printed"})
    response = invoke("show-container")
    assert response.exit_code == 0, response.output
    output = json.loads(response.output)
    assert output["provisioning_state"] == "Succeeded"
    assert "unrelated" not in output
    assert run.call_args.args[0][3:5] == ["container", "show"]
    assert run.call_count == 1


def test_delete_requires_yes_without_a_terminal(run):
    response = invoke("delete-container")
    assert response.exit_code == 2
    assert "--yes" in response.output
    run.assert_not_called()


def test_delete_cancelled_reports_target_without_operations(run):
    with patch("scripts.cli_cosmosdb.confirm_delete", return_value=False) as confirm:
        response = invoke("delete-container")
    assert response.exit_code == 0, response.output
    assert json.loads(response.output)["cancelled"] is True
    confirm.assert_called_once_with(TARGET.resource_id, False, resource_type="container")
    run.assert_not_called()


def test_delete_only_container_and_verify_completion(run):
    results(run, True, METADATA, None, False)
    response = invoke("delete-container", "--yes")
    assert response.exit_code == 0, response.output
    assert json.loads(response.output)["deleted"] is True
    assert [(call.args[0][3], call.args[0][4]) for call in run.call_args_list] == [
        ("container", "exists"),
        ("container", "show"),
        ("container", "delete"),
        ("container", "exists"),
    ]
    assert "--yes" in run.call_args_list[2].args[0]


@pytest.mark.parametrize("values", [(False,), (True, METADATA, None, True)])
def test_delete_missing_or_still_existing_is_not_success(values, run):
    results(run, *values)
    response = invoke("delete-container", "--yes")
    assert response.exit_code == 1
    assert '"deleted": true' not in response.output


def test_delete_rejects_product_container_even_with_yes(run):
    results(run, True, {"id": TARGET.resource_id, "resource": {"partitionKey": {"paths": ["/category"]}}})
    response = invoke("delete-container", "--yes")
    assert response.exit_code == 2
    assert "Refusing to delete" in response.output
    assert not any("delete" in call.args[0] for call in run.call_args_list)


@pytest.mark.parametrize(
    "failure",
    [FileNotFoundError(), subprocess.TimeoutExpired("az", 300)],
)
def test_az_missing_or_timeout_is_visible(failure, run):
    run.side_effect = failure
    response = invoke("show-container")
    assert response.exit_code == 1
    assert "Azure CLI" in response.output


def test_nonzero_exists_is_not_absence_and_sensitive_stderr_is_not_printed(run):
    run.return_value = subprocess.CompletedProcess([], 1, "", "sensitive-token")
    response = invoke("create-container")
    assert response.exit_code == 1
    assert "management-plane RBAC" in response.output
    assert "sensitive-token" not in response.output
    assert run.call_count == 1


def test_partial_completion_is_not_rolled_back(run):
    run.side_effect = [
        subprocess.CompletedProcess([], 0, "false", ""),
        subprocess.CompletedProcess([], 0, '{"id":"database-id"}', ""),
        subprocess.CompletedProcess([], 1, "", "forbidden"),
    ]
    response = invoke("create-container")
    assert response.exit_code == 1
    assert "Database was created" in response.output
    assert "not been rolled back" in response.output
    assert not any("delete" in call.args[0] for call in run.call_args_list)


@pytest.mark.parametrize("value", ['{"not":"a boolean"}', "null", '"false"', "invalid"])
def test_exists_invalid_result_is_not_absence(value, run):
    run.return_value = subprocess.CompletedProcess([], 0, value, "")
    response = invoke("create-container")
    assert response.exit_code == 1
    assert run.call_count == 1


@pytest.mark.parametrize(
    "metadata",
    [
        None,
        {},
        {"id": "id"},
        {"id": "id", "resource": {}},
        {"id": "id", "resource": {"partitionKey": {"paths": [12]}}},
        {**METADATA, "provisioningState": 42},
    ],
)
def test_show_invalid_metadata_is_not_success(metadata, run):
    results(run, metadata)
    assert invoke("show-container").exit_code == 1


@pytest.mark.parametrize(
    "options",
    [
        ["--subscription", "invalid"],
        ["--account-name", "not-an-account/path"],
        ["--database", " "],
        ["--container", "../products"],
        ["--throughput", "399"],
    ],
)
def test_invalid_inputs_do_not_execute_az(options, run):
    assert invoke("create-container", *options).exit_code == 2
    run.assert_not_called()


def test_management_defaults_and_overrides_are_separate_from_product_container(run):
    results(run, METADATA)
    response = CliRunner().invoke(
        app,
        ["tasks", "show-container"],
        env={
            "AZURE_SUBSCRIPTION_ID": SUBSCRIPTION,
            "AZURE_RESOURCE_GROUP": "test-group",
            "AZURE_COSMOS_DB_ACCOUNT_NAME": "test-account",
            "AZURE_COSMOS_DB_CONTAINER": "products",
            "AZURE_COSMOS_DB_TASK_CONTAINER": "tasks",
        },
    )
    assert response.exit_code == 0, response.output
    assert json.loads(response.output)["container"] == "tasks"


def test_management_explicit_arguments_override_environment(run):
    results(run, METADATA)
    response = CliRunner().invoke(
        app,
        ["tasks", "show-container", *OPTIONS, "--database", "explicit-db", "--container", "explicit-tasks"],
        env={
            "AZURE_SUBSCRIPTION_ID": "00000000-0000-0000-0000-000000000099",
            "AZURE_RESOURCE_GROUP": "environment-group",
            "AZURE_COSMOS_DB_ACCOUNT_NAME": "environment-account",
            "AZURE_COSMOS_DB_DATABASE": "environment-db",
            "AZURE_COSMOS_DB_TASK_CONTAINER": "environment-tasks",
        },
    )
    assert response.exit_code == 0, response.output
    output = json.loads(response.output)
    assert output["subscription"] == SUBSCRIPTION
    assert output["resource_group"] == "test-group"
    assert output["account"] == "test-account"
    assert output["database"] == "explicit-db"
    assert output["container"] == "explicit-tasks"


def test_missing_settings_and_help_do_not_execute_az(run):
    assert CliRunner().invoke(app, ["tasks", "show-container"]).exit_code == 2
    assert CliRunner().invoke(app, ["tasks", "--help"]).exit_code == 0
    assert CliRunner().invoke(app, ["tasks", "create-container", "--help"]).exit_code == 0
    run.assert_not_called()

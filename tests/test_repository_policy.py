"""Offline regression checks for the repository's workflow trust boundaries."""

import re
import tomllib
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"


def workflow(name: str) -> str:
    return (WORKFLOWS / f"{name}.yaml").read_text(encoding="utf-8")


def jobs(text: str) -> dict[str, str]:
    body = text.split("\njobs:\n", 1)[1]
    matches = list(re.finditer(r"^  ([a-zA-Z0-9_-]+):\n", body, re.MULTILINE))
    return {
        match.group(1): body[match.end() : matches[index + 1].start() if index + 1 < len(matches) else len(body)]
        for index, match in enumerate(matches)
    }


class RepositoryPolicyTests(unittest.TestCase):
    def test_uv_workflow_version_matches_project_requirement(self) -> None:
        config = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        requirement = config["tool"]["uv"]["required-version"]
        self.assertTrue(requirement.startswith("=="))
        version = requirement.removeprefix("==")
        for name in ("ci", "cd", "deploy"):
            text = workflow(name)
            with self.subTest(workflow=name):
                self.assertEqual(text.count("uses: astral-sh/setup-uv@"), text.count(f'version: "{version}"'))

    def test_legacy_workflows_are_consolidated(self) -> None:
        for filename in (
            "test.yaml",
            "docker.yaml",
            "docker-release.yaml",
            "ghcr-release.yaml",
            "azure-static-web-app.yaml",
            "github-pages.yaml",
        ):
            with self.subTest(filename=filename):
                self.assertFalse((WORKFLOWS / filename).exists())

    def test_owned_workflows_pin_actions_and_limit_credentials(self) -> None:
        for path in sorted(WORKFLOWS.glob("*")):
            if path.name in {"copilot-setup-steps.yml", "infra.yml"}:
                continue
            text = path.read_text(encoding="utf-8")
            with self.subTest(workflow=path.name):
                self.assertIn("permissions:\n  contents: read", text)
                self.assertIn("concurrency:", text)
                self.assertNotIn("write-all", text)
                self.assertNotIn("pull_request_target:", text)
                self.assertNotIn("secrets: inherit", text)
                for action in re.findall(r"^\s+-? ?uses: (\S+)", text, re.MULTILINE):
                    if not action.startswith("./"):
                        self.assertRegex(action, r"^[\w.-]+/[\w./-]+@[a-f0-9]{40}$")
                self.assertEqual(
                    text.count("uses: actions/checkout@"),
                    text.count("persist-credentials: false"),
                )
                for job_name, job in jobs(text).items():
                    with self.subTest(job=job_name):
                        if "steps:" in job:
                            self.assertIn("runs-on: ubuntu-24.04", job)
                            self.assertRegex(job, r"timeout-minutes: [1-9]\d*")

    def test_ci_events_matrix_and_strict_aggregate(self) -> None:
        text = workflow("ci")
        self.assertIn("push:\n    branches: [main]", text)
        self.assertIn("pull_request:\n    branches: [main]", text)
        self.assertIn("merge_group:", text)
        self.assertNotIn("feature/**", text)
        self.assertNotIn("copilot/**", text)
        self.assertNotIn('"3.10"', text)
        self.assertNotIn('"3.11"', text)
        self.assertNotIn('"3.12"', text)
        job_map = jobs(text)
        self.assertEqual(set(job_map), {"check", "test", "evaluation-compatibility", "docker", "docs", "ci-ok"})
        self.assertIn('python-version: ["3.13", "3.14"]', job_map["test"])
        self.assertIn("--locked --all-extras --no-dev --group test", job_map["test"])
        self.assertIn("uv build", job_map["test"])
        self.assertIn("make install-deps-ci format-check lint", job_map["check"])
        self.assertIn(".ci-tools/bicep build infra/main.bicep", job_map["check"])
        self.assertIn(".ci-tools/bicep lint infra/main.bicep", job_map["check"])
        self.assertIn("make hooks-check", job_map["check"])
        self.assertIn("make ci-test-docker", job_map["docker"])
        self.assertIn("if: always()", job_map["ci-ok"])
        self.assertIn("needs: [check, test, evaluation-compatibility, docker, docs]", job_map["ci-ok"])
        self.assertIn('all(.[]; .result == "success")', job_map["ci-ok"])
        self.assertNotIn("continue-on-error", text)

    def test_pr_title_reports_success_for_main_push_and_merge_queue(self) -> None:
        text = workflow("pr-title")
        self.assertIn("push:\n    branches: [main]", text)
        self.assertIn("merge_group:", text)
        self.assertIn("types: [opened, edited, synchronize, reopened, ready_for_review]", text)
        job = jobs(text)["pr-title"]
        self.assertNotIn("if:", job)
        self.assertIn("PR_TITLE: ${{ github.event.pull_request.title }}", job)
        self.assertIn('if [[ "$EVENT_NAME" != pull_request ]]; then', job)
        self.assertIn("exit 0", job)
        self.assertIn('if [[ ! "$PR_TITLE" =~ $pattern ]]; then', job)

    def test_evaluation_compatibility_is_preserved_without_paid_calls(self) -> None:
        job = jobs(workflow("ci"))["evaluation-compatibility"]
        self.assertIn('python-version: ["3.13", "3.14"]', job)
        self.assertIn("tests/test_evaluation_harness.py tests/test_evaluation_deepeval.py", job)
        self.assertNotIn("make lint-eval", job)
        self.assertIn("make test-eval EVAL_ARGS=--collect-only", job)
        self.assertNotIn("${{ secrets.", job)
        self.assertNotIn("ty check", job)
        self.assertNotIn("pyrefly check", job)

    def test_pages_build_is_read_only_and_deploy_uses_the_ci_artifact(self) -> None:
        build = jobs(workflow("ci"))["docs"]
        self.assertIn("mkdocs build --strict", build)
        self.assertIn("actions/upload-pages-artifact@", build)
        self.assertIn("github.event_name == 'push' && github.ref == 'refs/heads/main'", build)
        self.assertNotIn("write", build)
        self.assertNotIn("gh-deploy", build)
        deploy = workflow("pages")
        self.assertIn("workflows: [ci]", deploy)
        self.assertIn("github.event.workflow_run.conclusion == 'success'", deploy)
        self.assertIn("github.event.workflow_run.event == 'push'", deploy)
        self.assertIn("github.event.workflow_run.head_branch == 'main'", deploy)
        self.assertIn("github.event.workflow_run.head_repository.full_name == github.repository", deploy)
        self.assertIn("data.commit.sha !== context.payload.workflow_run.head_sha", deploy)
        self.assertIn("run-id: ${{ github.event.workflow_run.id }}", deploy)
        self.assertIn("path: pages-artifact/artifact.tar", deploy)
        self.assertIn("actions/deploy-pages@", deploy)
        self.assertIn("pages: write", deploy)
        self.assertIn("id-token: write", deploy)
        self.assertNotIn("actions/checkout@", deploy)

    def test_security_scans_cover_python_actions_and_dependencies(self) -> None:
        codeql = workflow("codeql")
        self.assertIn("language: [python, actions]", codeql)
        self.assertIn("build-mode: none", codeql)
        self.assertIn("merge_group:", codeql)
        self.assertIn("schedule:", codeql)
        config = (ROOT / ".github" / "codeql" / "codeql-config.yml").read_text(encoding="utf-8")
        self.assertIn("uses: security-extended", config)
        review = workflow("dependency-review")
        self.assertIn("merge_group:", review)
        self.assertIn("github.event.merge_group.base_sha", review)
        self.assertIn("github.event.merge_group.head_sha", review)
        self.assertIn("actions/dependency-review-action@", review)
        self.assertIn("config-file: .github/dependency-review-config.yml", review)
        config = (ROOT / ".github" / "dependency-review-config.yml").read_text(encoding="utf-8")
        self.assertIn("fail-on-severity: high", config)
        self.assertIn("vulnerability-check: true", config)
        self.assertIn("warn-only: false", config)
        for scope in ("runtime", "development", "unknown"):
            self.assertIn(f"  - {scope}", config)
        scorecard = workflow("scorecard")
        self.assertIn("ossf/scorecard-action@", scorecard)
        self.assertIn("publish_results: ${{ github.event.repository.visibility == 'public' }}", scorecard)
        self.assertIn("github/codeql-action/upload-sarif@", scorecard)

    def test_dependabot_cooldown_applies_to_every_ecosystem(self) -> None:
        text = (ROOT / ".github" / "dependabot.yaml").read_text(encoding="utf-8")
        entries = re.split(r"^  - package-ecosystem: ", text, flags=re.MULTILINE)[1:]
        self.assertEqual(
            {entry.splitlines()[0] for entry in entries},
            {"github-actions", "uv", "pre-commit", "docker", "devcontainers"},
        )
        for entry in entries:
            with self.subTest(ecosystem=entry.splitlines()[0]):
                self.assertIn("interval: weekly", entry)
                self.assertIn("cooldown:\n      default-days: 7", entry)
        secret_config = (ROOT / ".github" / "secret_scanning.yml").read_text(encoding="utf-8")
        self.assertIn("paths-ignore: []", secret_config)

    def test_cd_only_releases_the_successful_main_ci_commit(self) -> None:
        text = workflow("cd")
        self.assertIn("workflow_run:", text)
        self.assertIn("workflows: [ci]", text)
        self.assertNotIn("\n  push:", text)
        self.assertNotIn("workflow_dispatch:", text)
        for condition in (
            "github.event.workflow_run.conclusion == 'success'",
            "github.event.workflow_run.event == 'push'",
            "github.event.workflow_run.head_branch == 'main'",
            "github.event.workflow_run.head_repository.full_name == github.repository",
            "data.commit.sha !== context.payload.workflow_run.head_sha",
            "object.sha !== context.payload.workflow_run.head_sha",
        ):
            self.assertIn(condition, text)
        self.assertIn("googleapis/release-please-action@", text)
        self.assertIn("target-branch: main", text)
        self.assertIn("ref: ${{ needs.release.outputs.sha }}", text)
        self.assertNotIn("DOCKERHUB", text)
        self.assertNotIn("Azure/static-web-apps-deploy", text)

    def test_cd_tests_attests_and_promotes_one_immutable_multiarch_build(self) -> None:
        text = workflow("cd")
        self.assertEqual(text.count("uses: docker/build-push-action@"), 1)
        self.assertIn("if: steps.existing.outputs.digest == ''", text)
        self.assertIn("Reuse only an already attested build of this commit", text)
        self.assertIn('--source-digest "$SOURCE_SHA"', text)
        self.assertIn("uses: docker/setup-qemu-action@", text)
        self.assertIn("platforms: linux/amd64,linux/arm64", text)
        self.assertIn('docker pull --platform "$platform" "$IMAGE@$DIGEST"', text)
        self.assertIn("for platform in linux/amd64 linux/arm64", text)
        self.assertIn("scripts/smoke_test.py", text)
        self.assertIn("output-file: sbom-amd64.spdx.json", text)
        self.assertIn("output-file: sbom-arm64.spdx.json", text)
        self.assertIn("actions/attest-build-provenance@", text)
        self.assertIn("sbom-path: sbom-amd64.spdx.json", text)
        self.assertIn("sbom-path: sbom-arm64.spdx.json", text)
        self.assertLess(text.index("Pull and smoke-test"), text.index("Attest the tested build"))
        self.assertLess(text.index("Attest the ARM64"), text.index("Promote the same digest"))
        self.assertIn('if [[ "$PRERELEASE" == false ]]; then\n            tags+=(latest)', text)
        self.assertIn('--prefer-index=false --tag "$IMAGE:$tag" "$IMAGE@$DIGEST"', text)
        self.assertIn('[[ "$actual" == "$DIGEST" ]]', text)

    def test_deployment_verifies_the_main_signer_before_azure_digest_update(self) -> None:
        text = workflow("deploy")
        self.assertIn("github.ref == 'refs/heads/main'", text)
        self.assertIn("inputs.environment == 'staging' || inputs.environment == 'production'", text)
        self.assertIn("environment: ${{ inputs.environment }}", text)
        self.assertIn("^sha256:[a-f0-9]{64}$", text)
        self.assertIn('--signer-workflow "$GITHUB_REPOSITORY/.github/workflows/cd.yaml"', text)
        self.assertIn(".github/workflows/cd.yaml@refs/heads/main", text)
        self.assertIn("--source-ref refs/heads/main", text)
        self.assertIn('--source-digest "$SOURCE_SHA"', text)
        self.assertIn("--predicate-type https://spdx.dev/Document", text)
        self.assertLess(text.index("gh attestation verify"), text.index("uses: azure/login@"))
        self.assertLess(text.index("gh attestation verify"), text.index("az containerapp update"))
        self.assertIn('--image "$IMAGE@$DIGEST"', text)
        self.assertIn('[[ "$mode" == Single ]]', text)
        self.assertIn("properties.latestReadyRevisionName", text)
        self.assertIn('[[ "$actual" == "$IMAGE@$DIGEST" ]]', text)
        for variable in (
            "AZURE_CLIENT_ID",
            "AZURE_TENANT_ID",
            "AZURE_SUBSCRIPTION_ID",
            "RESOURCE_GROUP",
            "CONTAINER_APP_NAME",
        ):
            self.assertIn(f"vars.{variable}", text)
        self.assertIn("--attempts 30 --interval 5", text)

    def test_manual_rollback_cannot_select_an_arbitrary_ref_or_skip_staging(self) -> None:
        text = workflow("deploy-manual")
        job_map = jobs(text)
        self.assertEqual(set(job_map), {"staging", "production"})
        self.assertIn("github.ref == 'refs/heads/main'", job_map["staging"])
        self.assertIn("github.ref == 'refs/heads/main'", job_map["production"])
        self.assertIn("needs: [staging]", job_map["production"])
        self.assertNotIn("ref:", text)
        self.assertNotIn("image:", text)
        self.assertNotIn("skip", text)
        cd_jobs = jobs(workflow("cd"))
        self.assertIn("needs: [release, build, staging]", cd_jobs["production"])


if __name__ == "__main__":
    unittest.main()

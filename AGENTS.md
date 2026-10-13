# Contributor and agent guide

Use uv and the committed lockfile. Start with `make install-deps-dev`.
Run focused `uv run --locked --all-extras pytest tests/test_<area>.py --no-cov`
tests while iterating; run `make ci-test` before submitting application changes.
Documentation builds use `make ci-test-docs`; Docker checks use
`make ci-test-docker`. Compile infrastructure with
`az bicep build --file infra/main.bicep`.

- Keep changes scoped to the task and add regression tests.
- Preserve inward Clean Architecture dependencies and centralized settings.
- Do not log settings, tokens, principal headers, or connection strings.
- Never run paid LLM evaluations or deploy Azure resources without approval.
- Do not remove security gates, change environment protections, force-push,
  delete Azure resources, or commit build output.
- Keep Actions SHA-pinned, checkout credentials disabled, permissions
  job-scoped, release caches disabled, and deployments digest-pinned.
- Verify external API/tool claims against installed versions; do not assume
  that a review's proposed version or feature exists.

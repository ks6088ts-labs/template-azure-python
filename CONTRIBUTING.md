# Contributing

Install uv and run `make install-deps-dev`. Run focused pytest tests first,
then `make ci-test`, `make ci-test-docs`, and `make ci-test-docker` where Docker
is available. Run `az bicep build --file infra/main.bicep` for infrastructure changes.

Keep the domain and application layers framework-independent. Add regression
tests for changed behavior and preserve optional CLI samples and persistence
adapters. Never use real Azure credentials in tests or enable paid evaluations
without explicit consent.

Use Conventional Commit PR titles (for example `fix: handle stale task updates`);
squash merges allow release-please to generate versions and release notes.
Security reports belong in private reporting, not public issues.

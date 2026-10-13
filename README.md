[![ci](https://github.com/OWNER/template-azure-python/actions/workflows/ci.yaml/badge.svg?branch=main)](https://github.com/OWNER/template-azure-python/actions/workflows/ci.yaml)
[![release](https://github.com/OWNER/template-azure-python/actions/workflows/cd.yaml/badge.svg)](https://github.com/OWNER/template-azure-python/actions/workflows/cd.yaml)
[![docs](https://github.com/OWNER/template-azure-python/actions/workflows/pages.yaml/badge.svg)](https://github.com/OWNER/template-azure-python/actions/workflows/pages.yaml)

# template-azure-python

A template repository for Python projects.

The FastAPI application includes a typed Task CRUD vertical slice that demonstrates
Clean Architecture boundaries, repository ports/adapters, explicit composition, strict
type checking, and CI-enforced import rules. See the architecture guide below before
copying the pattern for a new feature.

## Quick start

Python 3.13+ is required; the default interpreter is Python 3.14.

```shell
make install-deps-dev
uv run --locked python -m template_azure_python
```

Use `/healthz` and `/readyz` for probes. Local API documentation is available
at `/docs`; production disables it by default. Azure deployment uses Easy Auth,
environment-scoped OIDC, verified image digests, and production approval.
Configure the prerequisites in [Deployment](docs/deployment.md) before enabling CD.

Runtime dependencies exclude optional CLI samples, Functions, and storage SDKs.
Development installation enables those extras for the existing sample tests.
See [SECURITY.md](SECURITY.md) and [CONTRIBUTING.md](CONTRIBUTING.md).

## Documentation

| Topic | English | 日本語 |
| --- | --- | --- |
| Getting started | [Guide](docs/index.md) | [はじめに](docs/index.ja.md) |
| Local development | [Guide](docs/scripts.md) | [ローカル開発](docs/scripts.ja.md) |
| Architecture | [Guide](docs/architecture/index.md) | [アーキテクチャ](docs/architecture/index.ja.md) |
| Data engineering | [Guide](docs/dbt/index.md) | [dbt・DuckDB 入門](docs/dbt/index.ja.md) |
| Microsoft Foundry | [Guide](docs/foundry.md) | [ガイド](docs/foundry.ja.md) |
| Azure Cosmos DB | [Guide](docs/cosmosdb.md) | [ガイド](docs/cosmosdb.ja.md) |
| Messaging | [Guide](docs/messaging.md) | [メッセージング](docs/messaging.ja.md) |
| Monitoring and logs | [Guide](docs/monitoring.md) | [監視とログ](docs/monitoring.ja.md) |
| Deployment | [Guide](docs/deployment.md) | [ガイド](docs/deployment.ja.md) |

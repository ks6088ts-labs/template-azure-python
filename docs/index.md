# Getting started

Use this template to develop Python applications and try Azure SDK samples.
The same FastAPI app runs locally, on Azure Functions, and on Azure Container Apps.

## Run the app locally first

You do not need Azure resources or an Azure sign-in.
[Install Python, uv, and Make](scripts.md), then run these commands from the
repository root:

```shell
make install-deps-dev
uv run --locked python -m scripts.template serve-container-apps
```

Check the API from another terminal:

```shell
curl http://127.0.0.1:8000/tasks
```

An initial response of `[]` confirms that the app is running. InMemory is the default storage backend.
See [Cosmos DB](cosmosdb.md) for persistence and management CLI commands.
Open <http://127.0.0.1:8000/docs> in a browser to try the API.
Press `Ctrl+C` in the server terminal to stop it.

## Choose a guide by goal

| I want to... | Guide |
| --- | --- |
| Set up development and run the API, tests, or Docker | [Local development](scripts.md) |
| Try AI models and agents | [Microsoft Foundry](foundry.md) |
| Store and retrieve data | [Azure Cosmos DB](cosmosdb.md) |
| Send and receive events or messages | [Messaging](messaging.md) |
| Read Azure monitoring data and logs | [Monitoring and logs](monitoring.md) |
| Publish the app, image, or documentation | [Deployment](deployment.md) |

## Suggested workflow

1. **Check locally**: start the API above, then follow the development guide to run tests.
2. **Try the Azure samples you need**: check each guide for settings and access permissions.
3. **Publish**: choose a deployment target and check the API or site after deployment.

Azure samples use existing resources. Each guide explains how to prepare them
and highlights costs or deletion risks. You do not need to run every sample in order.

import uvicorn

from template_azure_python.settings import get_project_settings


def main() -> None:
    settings = get_project_settings()
    uvicorn.run(
        "template_azure_python.api:create_app",
        factory=True,
        host=settings.host,
        port=settings.port,
        log_config=None,
        server_header=False,
        proxy_headers=True,
        forwarded_allow_ips=settings.forwarded_allow_ips,
        timeout_graceful_shutdown=30,
    )


if __name__ == "__main__":
    main()

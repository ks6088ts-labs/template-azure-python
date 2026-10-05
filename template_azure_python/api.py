from fastapi import FastAPI

from template_azure_python.routers import root
from template_azure_python.telemetry import configure_api_telemetry


def create_app() -> FastAPI:
    configure_api_telemetry()
    application = FastAPI()
    application.include_router(root.router)
    return application


app = create_app()

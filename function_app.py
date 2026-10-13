import azure.functions as func

from template_azure_python.api import create_app

app = func.AsgiFunctionApp(app=create_app(), http_auth_level=func.AuthLevel.ANONYMOUS)

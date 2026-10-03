from fastapi import FastAPI

from template_azure_python.routers import root

app = FastAPI()
app.include_router(root.router)

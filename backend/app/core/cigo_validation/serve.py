"""Local process for the nonpublic mock demo. It does not start the rest of Nova."""
from fastapi import FastAPI

from app.core.cigo_validation.router import router

app = FastAPI(title="CIGO validation demo")
app.include_router(router)

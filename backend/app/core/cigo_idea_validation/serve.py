"""Local process for the nonpublic worksheet. It does not start the rest of Nova."""
from fastapi import FastAPI

from app.core.cigo_idea_validation.router import router

app = FastAPI(title="CIGO consumer idea validation")
app.include_router(router)

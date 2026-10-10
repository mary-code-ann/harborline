"""Harborline web app. One procedure-gated collections agent."""

from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.routes import router
from app.db.session import SessionLocal


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.session_factory = SessionLocal
    yield


app = FastAPI(title="Harborline", lifespan=lifespan)
app.include_router(router)

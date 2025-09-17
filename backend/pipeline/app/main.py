# app/main.py

"""
Main FastAPI application entry point.

This module creates and configures the `FastAPI` app for the bytesophos project.
It:

* Loads environment variables from a `.env` file if present.
* Connects to and disconnects from the database on startup/shutdown.
* Sets up CORS so that any origin can access the API.
* Registers all application routers under the `/api` prefix.
* Exposes a `/api/health` route for basic health checking.

Routers included:
    - auth, users, conversations, messages, documents,
      document_chunks, rag_queries, retrieved_chunks, upload, repos and websocket.
"""

import os
from pathlib import Path
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

from app.db import connect_db, disconnect_db
from app.routes import (
    auth,
    users, 
    conversations, messages, documents, document_chunks,
    rag_queries, retrieved_chunks,
    upload, repos, websocket
)

DOTENV_PATH = Path(__file__).resolve().parent.parent.parent / ".env"
if DOTENV_PATH.exists():
    load_dotenv(DOTENV_PATH)

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Handle startup and shutdown events.

    Connects to the database when the app starts and disconnects
    when the app stops.

    Args:
        app: The FastAPI application instance.

    Yields:
        None: Control is passed to FastAPI to continue app startup.
    """
    await connect_db()
    try:
        yield
    finally:
        await disconnect_db()

app = FastAPI(
    title="bytesophos API",
    version="2.0.0",
    description="API documentation for bytesophos project",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

for router in [
    auth.router,
    users.router,
    conversations.router, messages.router, documents.router, document_chunks.router,
    rag_queries.router, retrieved_chunks.router,
    upload.router, repos.router
]:
    app.include_router(router, prefix="/api")

app.include_router(websocket.router)

@app.get("/api/health")
def health():
    """Basic health check endpoint.

    Returns:
        dict: Simple JSON indicating the API is up, e.g. ``{"status": "ok"}``.
    """
    return {"status": "ok"}
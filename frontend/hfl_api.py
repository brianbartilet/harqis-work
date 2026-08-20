"""Standalone authenticated API for the canonical HFL Activity Corpus."""

from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI

from config import get_settings
from modules.hfl_corpus.api import router as hfl_corpus_api_router
from modules.hfl_corpus.corpus import corpus_index
from modules.hfl_corpus.remote import close_remote_http_client


@asynccontextmanager
async def lifespan(_: FastAPI):
    """Warm the canonical corpus index and release pooled clients on shutdown."""
    if not get_settings().hfl_corpus_api_url.strip():
        await asyncio.to_thread(corpus_index.documents, True)
    try:
        yield
    finally:
        close_remote_http_client()


app = FastAPI(
    title="HARQIS HFL Activity Corpus API",
    summary="Capture and query canonical Homework-for-Life entries.",
    description=(
        "Authenticated API for writing the canonical Markdown Activity Corpus and its "
        "best-effort Elasticsearch projection, plus searching and retrieving entries."
    ),
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    lifespan=lifespan,
)
app.include_router(hfl_corpus_api_router)


@app.get("/health", tags=["operations"], summary="Service health")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "hfl-api"}


if __name__ == "__main__":
    uvicorn.run(
        "hfl_api:app",
        host=os.environ.get("HFL_API_HOST", "0.0.0.0"),
        port=int(os.environ.get("HFL_API_PORT", "8082")),
        server_header=False,
    )

"""FastAPI application — production entry point.

Usage: uvicorn lightspeed_agentic.app:app --host 0.0.0.0 --port 8080
"""

from __future__ import annotations

import logging
import os

from fastapi import FastAPI

from lightspeed_agentic.factory import create_provider
from lightspeed_agentic.routes import build_router

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

app = FastAPI(title="lightspeed-agentic-sandbox")

provider = create_provider()
router = build_router(
    provider,
    skills_dir=os.environ.get("LIGHTSPEED_SKILLS_DIR", "/app/skills"),
)
app.include_router(router, prefix="/v1/agent")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}

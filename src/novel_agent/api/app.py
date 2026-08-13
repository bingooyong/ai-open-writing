"""FastAPI 应用工厂。默认 CORS 仅 localhost。"""

from __future__ import annotations

from urllib.parse import urlparse

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.engine import Engine

from novel_agent import __version__
from novel_agent.api.routes import router
from novel_agent.config import Settings, get_settings
from novel_agent.domain.db import build_engine, create_all


def local_cors_origins(raw: str) -> list[str]:
    origins: list[str] = []
    for item in raw.split(","):
        origin = item.strip()
        if not origin:
            continue
        host = urlparse(origin).hostname
        if host in {"localhost", "127.0.0.1", "::1"}:
            origins.append(origin)
    return origins


def create_app(settings: Settings | None = None, engine: Engine | None = None) -> FastAPI:
    resolved = settings or get_settings()
    db_engine = engine or build_engine(resolved.db_path)
    create_all(db_engine)
    application = FastAPI(title="novel-agent writing desk", version=__version__)
    application.state.settings = resolved
    application.state.engine = db_engine
    application.add_middleware(
        CORSMiddleware,
        allow_origins=local_cors_origins(resolved.cors_origins),
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    application.include_router(router)
    return application

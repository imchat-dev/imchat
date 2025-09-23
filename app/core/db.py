# app/core/db.py
from __future__ import annotations

import urllib.parse
from typing import Tuple

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings


def _encode(component: str | None) -> str:
    return urllib.parse.quote_plus(component or "")


def build_database_url() -> str:
    user = _encode(settings.db_user)
    password = _encode(settings.db_pass)
    host = settings.db_host or "localhost"
    port = settings.db_port or 5432
    database = settings.db_name or "postgres"
    return f"postgresql+asyncpg://{user}:{password}@{host}:{port}/{database}"


def create_engine_and_sessionmaker() -> Tuple[AsyncEngine, async_sessionmaker[AsyncSession]]:
    engine = create_async_engine(
        build_database_url(),
        pool_size=5,
        max_overflow=5,
        pool_pre_ping=True,
    )
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    return engine, session_factory

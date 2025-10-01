# app/core/lifespan.py
from contextlib import asynccontextmanager
import logging
import uuid

from sqlalchemy import select
from app.adapters.vectorstores.chroma_adapter import build_or_refresh_index, load_or_create_chroma
from app.core.config import settings
from app.core.db import create_engine_and_sessionmaker
from app.core.rate_limit import RateLimiter
from app.models.db_models import Tenant

logger = logging.getLogger(__name__)


def _split_sources(raw: str) -> list[str]:
    return [s.strip() for s in raw.split(",") if s.strip()]


async def _get_tenant_ids_from_db(session_factory):
    """Get all tenant UUIDs from database"""
    async with session_factory() as session:
        stmt = select(Tenant.id)
        result = await session.execute(stmt)
        tenant_uuids = result.scalars().all()
        return list(tenant_uuids)


def _get_default_tenant_ids():
    """Get list of tenant IDs to initialize (fallback)"""
    try:
        # Try to parse default_tenant_id as UUID
        return [uuid.UUID(settings.default_tenant_id)]
    except ValueError:
        # If it's not a valid UUID, return empty list
        logger.warning("default_tenant_id is not a valid UUID: %s", settings.default_tenant_id)
        return []


@asynccontextmanager
async def lifespan(app):
    engine, session_factory = create_engine_and_sessionmaker()
    app.state.db_engine = engine
    app.state.db_sessionmaker = session_factory
    logger.info("SQLAlchemy engine and session factory created.")

    # Load tenant IDs from database
    try:
        tenant_ids = await _get_tenant_ids_from_db(session_factory)
        if not tenant_ids:
            logger.warning("No tenants found in database. Using default tenant.")
            # Get or create default tenant
            async with session_factory() as session:
                async with session.begin():
                    stmt = select(Tenant).where(Tenant.name == settings.default_tenant_id)
                    result = await session.execute(stmt)
                    default_tenant = result.scalar_one_or_none()
                    if default_tenant:
                        tenant_ids = [default_tenant.id]
                    else:
                        logger.error("Default tenant not found. Please run migrations first.")
                        tenant_ids = _get_default_tenant_ids()
    except Exception as e:
        logger.error("Failed to load tenant IDs: %s", e)
        tenant_ids = _get_default_tenant_ids()
    
    app.state.tenant_ids = tenant_ids
    logger.info("Initialized with %d tenant(s): %s", len(tenant_ids), tenant_ids)

    app.state.rate_limiter = RateLimiter(
        max_requests=settings.rate_limit_max_requests,
        window_seconds=settings.rate_limit_window_seconds,
    )
    logger.info(
        "Rate limiter ready (max %s requests in %s s).",
        settings.rate_limit_max_requests,
        settings.rate_limit_window_seconds,
    )

    default_collection_id = None
    try:
        if settings.init_vector_on_startup:
            logger.info("Initializing and building vector collections...")
            try:
                default_sources = _split_sources(settings.default_sources or "")
                for tenant_id in tenant_ids:
                    if default_sources:
                        build_or_refresh_index(
                            sources=default_sources,
                            persist_dir=settings.persist_dir,
                            tenant_id=str(tenant_id),
                            collection_name=str(tenant_id),  # Use tenant_id as collection name
                        )
                    if default_collection_id is None:
                        default_collection_id = str(tenant_id)
                logger.info("Vector collections prepared.")
            except Exception as e:  # pragma: no cover
                logger.warning("Vector collection build failed: %s", e)
            
            if default_collection_id is None and tenant_ids:
                default_collection_id = str(tenant_ids[0])
                
            app.state.vectorstore = load_or_create_chroma(
                settings.persist_dir,
                collection_name=default_collection_id,
            )
            logger.info("Vector store loaded (default collection: %s).", default_collection_id)
        if settings.init_llm_on_startup:
            logger.info("Initializing LLM...")
            from app.adapters.llm.openai_provider import get_chat_llm

            app.state.llm = get_chat_llm()
            logger.info("LLM ready.")
    except Exception as e:  # pragma: no cover
        logger.error("Error initializing resources: %s", e)
        raise e

    try:
        yield
    finally:
        logger.info("Shutting down... Disposing SQLAlchemy engine...")
        try:
            await engine.dispose()
        except Exception as e:  # pragma: no cover
            logger.warning("Engine dispose failed: %s", e)








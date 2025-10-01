# app/core/lifespan.py
from contextlib import asynccontextmanager
import logging

from app.adapters.vectorstores.chroma_adapter import build_or_refresh_index, load_or_create_chroma
from app.core.config import settings
from app.core.db import create_engine_and_sessionmaker
from app.core.rate_limit import RateLimiter
from app.core.tenant_config import ProfileConfig, TenantConfig

logger = logging.getLogger(__name__)


def _split_sources(raw: str) -> list[str]:
    return [s.strip() for s in raw.split(",") if s.strip()]


def _default_tenant_fallback():
    profile_keys = [role.strip() for role in settings.allowed_roles.split(",") if role.strip()]
    if not profile_keys:
        profile_keys = ["default"]
    default_sources = _split_sources(settings.default_sources or "")
    profiles = {
        key: ProfileConfig(
            key=key,
            display_name=key.capitalize(),
            vector_collection=f"{settings.default_tenant_id}_{key}",
            source_paths=default_sources,
            tools=[],  # No tools enabled
        )
        for key in profile_keys
    }
    tenant_cfg = TenantConfig(
        tenant_id=settings.default_tenant_id,
        default_profile=profile_keys[0],
        profiles=profiles,
    )
    return {tenant_cfg.tenant_id: tenant_cfg}


@asynccontextmanager
async def lifespan(app):
    engine, session_factory = create_engine_and_sessionmaker()
    app.state.db_engine = engine
    app.state.db_sessionmaker = session_factory
    logger.info("SQLAlchemy engine and session factory created.")

    # Use fallback configuration instead of loading from file
    tenant_registry = _default_tenant_fallback()
    app.state.tenant_registry = tenant_registry
    logger.info("Using fallback tenant configuration with %d tenant(s).", len(tenant_registry))

    app.state.rate_limiter = RateLimiter(
        max_requests=settings.rate_limit_max_requests,
        window_seconds=settings.rate_limit_window_seconds,
    )
    logger.info(
        "Rate limiter ready (max %s requests in %s s).",
        settings.rate_limit_max_requests,
        settings.rate_limit_window_seconds,
    )

    default_collection = None
    try:
        if settings.init_vector_on_startup:
            logger.info("Initializing and building vector collections...")
            try:
                for tenant_id in tenant_registry.tenant_ids():
                    tenant_cfg = tenant_registry.get_tenant(tenant_id)
                    for profile in tenant_cfg.profiles.values():
                        if profile.source_paths:
                            build_or_refresh_index(
                                sources=profile.source_paths,
                                persist_dir=settings.persist_dir,
                                tenant_id=tenant_id,
                                profile_key=profile.key,
                                collection_name=profile.vector_collection,
                            )
                        if default_collection is None:
                            default_collection = profile.vector_collection
                logger.info("Vector collections prepared.")
            except Exception as e:  # pragma: no cover
                logger.warning("Vector collection build failed: %s", e)
            if default_collection is None:
                tenant_ids = tenant_registry.tenant_ids()
                if tenant_ids:
                    fallback_tenant_id = (
                        settings.default_tenant_id if settings.default_tenant_id in tenant_registry.tenant_ids() else tenant_ids[0]
                    )
                    fallback_tenant = tenant_registry.get_tenant(fallback_tenant_id)
                    default_profile = fallback_tenant.default_profile
                    default_collection = fallback_tenant.get_profile(default_profile).vector_collection
            app.state.vectorstore = load_or_create_chroma(
                settings.persist_dir,
                collection_name=default_collection,
            )
            logger.info("Vector store loaded (default handle: %s).", default_collection)
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

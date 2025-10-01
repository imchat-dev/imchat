# app/main.py
import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select

from app.api.routes.chat import router as chat_router
from app.api.routes.downloads import router as downloads_router
from app.api.routes.health import router as health_router
# from app.api.routes.sessions import router as sessions_router  # Removed - using tenant-based endpoints
from app.api.routes.tenants import router as tenants_router
from app.api.routes.tenant_sessions import router as tenant_sessions_router
from app.api.routes.tenant_messages import router as tenant_messages_router
from app.api.routes.tenant_docs import router as tenant_docs_router
from app.core.lifespan import lifespan
from app.core.config import settings

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="RAG Chatbot API",
    description="Document Based Chatbot API",
    version="1.0.0",
    lifespan=lifespan,
)

# Register specific routes before generic ones to avoid conflicts
app.include_router(tenants_router, prefix="/chat", tags=["tenants"])
app.include_router(tenant_sessions_router, prefix="/chat", tags=["tenant-sessions"])
app.include_router(tenant_messages_router, prefix="/chat", tags=["tenant-messages"])
app.include_router(tenant_docs_router, prefix="/chat", tags=["tenant-docs"])
# app.include_router(sessions_router, prefix="/chat", tags=["sessions"])  # Removed - using tenant-based endpoints
app.include_router(chat_router, prefix="/chat", tags=["chat"])
app.include_router(downloads_router, tags=["downloads"])
app.include_router(health_router, tags=["health"])

# Parse CORS origins from environment
cors_origins = settings.cors_origins.split(",") if settings.cors_origins != "*" else ["*"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=settings.cors_allow_credentials,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Health endpoint is handled by health_router

if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)


# app/main.py
import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select

from app.api.routes.chat import router as chat_router
from app.api.routes.downloads import router as downloads_router
from app.api.routes.health import router as health_router
from app.api.routes.sessions import router as sessions_router
from app.core.lifespan import lifespan

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="RAG Chatbot API",
    description="Document Based Chatbot API",
    version="1.0.0",
    lifespan=lifespan,
)

app.include_router(chat_router, prefix="/chat", tags=["chat"])
app.include_router(sessions_router, prefix="/chat", tags=["sessions"])
app.include_router(downloads_router, tags=["downloads"])
app.include_router(health_router, tags=["health"])

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health_check():
    try:
        session_factory = app.state.db_sessionmaker
    except AttributeError as exc:  # pragma: no cover
        return {"status": "degraded", "error": str(exc)}

    try:
        async with session_factory() as session:
            result = await session.execute(select(1))
            ok = result.scalar() == 1
        return {"status": "healthy", "db": ok}
    except Exception as e:
        return {"status": "degraded", "error": str(e)}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)


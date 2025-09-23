from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import select

router = APIRouter()


@router.get("/health")
async def health_check(request: Request):
    session_factory = getattr(request.app.state, "db_sessionmaker", None)
    if session_factory is None:
        raise HTTPException(status_code=503, detail="Veritabani hazir degil")
    try:
        async with session_factory() as session:
            result = await session.execute(select(1))
            ok = result.scalar() == 1
        return {"status": "healthy", "db": ok}
    except Exception as e:
        return {"status": "degraded", "error": str(e)}

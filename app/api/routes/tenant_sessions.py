# app/api/routes/tenant_sessions.py
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Request, Query
from sqlalchemy import select, insert, update, delete, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import sanitize_identifier, SecurityError
from app.models.db_models import ChatSession, Tenant
from app.models.schemas import SessionCreateRequest, SessionResponse

router = APIRouter()


def _get_session_factory(request: Request):
    session_factory = getattr(request.app.state, "db_sessionmaker", None)
    if session_factory is None:
        raise HTTPException(status_code=503, detail="Veritabani hazir degil")
    return session_factory


def _to_iso_with_tz(dt) -> Optional[str]:
    if dt is None:
        return None
    try:
        if getattr(dt, "tzinfo", None) is None:
            return dt.replace(tzinfo=timezone.utc).astimezone(timezone.utc).isoformat()
        return dt.astimezone(timezone.utc).isoformat()
    except Exception:
        return str(dt)


def _validate_uuid(uuid_str: str, field_name: str) -> uuid.UUID:
    """Validate and convert string to UUID"""
    try:
        return uuid.UUID(uuid_str)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Gecersiz {field_name} format")


@router.post("/{tenant_id}/sessions", response_model=SessionResponse)
async def create_session(tenant_id: str, request: Request, payload: SessionCreateRequest):
    """Create a new session for a tenant"""
    session_factory = _get_session_factory(request)
    
    try:
        safe_tenant_id = _validate_uuid(tenant_id, "tenant_id")
    except SecurityError as exc:
        raise HTTPException(status_code=400, detail="Gecersiz parametre") from exc

    # Get client info
    xff = request.headers.get("x-forwarded-for", "")
    forwarded_ip = xff.split(",")[0].strip() if xff else None
    client_ip = forwarded_ip or (request.client.host if request.client else "0.0.0.0")
    user_agent = request.headers.get("user-agent", "-")

    async with session_factory() as session:
        async with session.begin():
            # Verify tenant exists
            tenant_stmt = select(Tenant).where(Tenant.id == safe_tenant_id)
            tenant_result = await session.execute(tenant_stmt)
            tenant = tenant_result.scalar_one_or_none()
            
            if not tenant:
                raise HTTPException(status_code=404, detail="Tenant bulunamadi")
            
            session_id = uuid.uuid4()
            started_at = datetime.now(timezone.utc)
            
            new_session = ChatSession(
                id=session_id,
                tenant_id=safe_tenant_id,
                title=payload.title,
                client_ip=client_ip,
                user_agent=user_agent,
                started_at=started_at,
                last_activity_at=started_at
            )
            session.add(new_session)
            await session.flush()
            
            return SessionResponse(
                id=session_id,
                title=payload.title,
                started_at=started_at.isoformat(),
                last_activity_at=started_at.isoformat()
            )


@router.get("/{tenant_id}/sessions", response_model=List[SessionResponse])
async def get_sessions(
    tenant_id: str, 
    request: Request, 
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0)
):
    """Get sessions for a tenant and user"""
    session_factory = _get_session_factory(request)
    
    try:
        safe_tenant_id = _validate_uuid(tenant_id, "tenant_id")
    except SecurityError as exc:
        raise HTTPException(status_code=400, detail="Gecersiz parametre") from exc

    async with session_factory() as session:
        stmt = (
            select(ChatSession)
            .where(
                ChatSession.tenant_id == safe_tenant_id
            )
            .order_by(func.coalesce(ChatSession.last_activity_at, ChatSession.started_at).desc())
            .offset(offset)
            .limit(limit)
        )
        result = await session.execute(stmt)
        sessions = result.scalars().all()
        
        return [
            SessionResponse(
                id=session.id,
                title=session.title,
                started_at=_to_iso_with_tz(session.started_at),
                last_activity_at=_to_iso_with_tz(session.last_activity_at)
            )
            for session in sessions
        ]


@router.get("/{tenant_id}/sessions/{session_id}", response_model=SessionResponse)
async def get_session(tenant_id: str, session_id: str, request: Request):
    """Get a specific session"""
    session_factory = _get_session_factory(request)
    
    try:
        safe_tenant_id = _validate_uuid(tenant_id, "tenant_id")
        safe_session_id = _validate_uuid(session_id, "session_id")
    except SecurityError as exc:
        raise HTTPException(status_code=400, detail="Gecersiz parametre") from exc

    async with session_factory() as session:
        stmt = select(ChatSession).where(
            ChatSession.id == safe_session_id,
            ChatSession.tenant_id == safe_tenant_id
        )
        result = await session.execute(stmt)
        chat_session = result.scalar_one_or_none()
        
        if not chat_session:
            raise HTTPException(status_code=404, detail="Session bulunamadi")
            
        return SessionResponse(
            id=chat_session.id,
            title=chat_session.title,
            started_at=_to_iso_with_tz(chat_session.started_at),
            last_activity_at=_to_iso_with_tz(chat_session.last_activity_at)
        )


@router.delete("/{tenant_id}/sessions/{session_id}")
async def delete_session(tenant_id: str, session_id: str, request: Request):
    """Delete a session"""
    session_factory = _get_session_factory(request)
    
    try:
        safe_tenant_id = _validate_uuid(tenant_id, "tenant_id")
        safe_session_id = _validate_uuid(session_id, "session_id")
    except SecurityError as exc:
        raise HTTPException(status_code=400, detail="Gecersiz parametre") from exc

    async with session_factory() as session:
        async with session.begin():
            # Check if session exists
            stmt = select(ChatSession).where(
                ChatSession.id == safe_session_id,
                ChatSession.tenant_id == safe_tenant_id
            )
            result = await session.execute(stmt)
            chat_session = result.scalar_one_or_none()
            
            if not chat_session:
                raise HTTPException(status_code=404, detail="Session bulunamadi")
            
            # Delete session (cascade will handle messages)
            await session.delete(chat_session)
            
            return {"status": "ok", "deleted": True, "session_id": str(safe_session_id)}


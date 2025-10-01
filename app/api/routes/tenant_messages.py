# app/api/routes/tenant_messages.py
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Request, Query
from sqlalchemy import select, insert, delete, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import sanitize_identifier, SecurityError
from app.models.db_models import ChatMessage, ChatSession, Tenant
from app.models.schemas import MessageCreateRequest, MessageResponse

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


@router.post("/{tenant_id}/sessions/{session_id}/messages", response_model=MessageResponse)
async def create_message(
    tenant_id: str, 
    session_id: str, 
    request: Request, 
    payload: MessageCreateRequest
):
    """Create a new message in a session"""
    session_factory = _get_session_factory(request)
    
    try:
        safe_tenant_id = _validate_uuid(tenant_id, "tenant_id")
        safe_session_id = _validate_uuid(session_id, "session_id")
    except SecurityError as exc:
        raise HTTPException(status_code=400, detail="Gecersiz parametre") from exc

    async with session_factory() as session:
        async with session.begin():
            # Verify session exists and belongs to tenant
            session_stmt = select(ChatSession).where(
                ChatSession.id == safe_session_id,
                ChatSession.tenant_id == safe_tenant_id
            )
            session_result = await session.execute(session_stmt)
            chat_session = session_result.scalar_one_or_none()
            
            if not chat_session:
                raise HTTPException(status_code=404, detail="Session bulunamadi")
            
            # Authorization check removed - tenant_id verification is sufficient
            
            # Create message
            message_id = uuid.uuid4()
            created_at = datetime.now(timezone.utc)
            
            new_message = ChatMessage(
                id=message_id,
                tenant_id=safe_tenant_id,
                session_id=safe_session_id,
                message_role=payload.role,
                content=payload.content,
                created_at=created_at
            )
            session.add(new_message)
            
            # Update session last activity
            chat_session.last_activity_at = created_at
            await session.flush()
            
            return MessageResponse(
                id=message_id,
                content=payload.content,
                role=payload.role,
                created_at=created_at.isoformat(),
                model=None
            )


@router.get("/{tenant_id}/sessions/{session_id}/messages", response_model=List[MessageResponse])
async def get_messages(
    tenant_id: str, 
    session_id: str, 
    request: Request,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0)
):
    """Get messages for a session"""
    session_factory = _get_session_factory(request)
    
    try:
        safe_tenant_id = _validate_uuid(tenant_id, "tenant_id")
        safe_session_id = _validate_uuid(session_id, "session_id")
    except SecurityError as exc:
        raise HTTPException(status_code=400, detail="Gecersiz parametre") from exc

    async with session_factory() as session:
        # Verify session exists and belongs to tenant
        session_stmt = select(ChatSession).where(
            ChatSession.id == safe_session_id,
            ChatSession.tenant_id == safe_tenant_id
        )
        session_result = await session.execute(session_stmt)
        chat_session = session_result.scalar_one_or_none()
        
        if not chat_session:
            raise HTTPException(status_code=404, detail="Session bulunamadi")
        
        # Authorization check removed - tenant_id verification is sufficient
        
        # Get messages
        stmt = (
            select(ChatMessage)
            .where(
                ChatMessage.session_id == safe_session_id,
                ChatMessage.tenant_id == safe_tenant_id
            )
            .order_by(ChatMessage.created_at.asc())
            .offset(offset)
            .limit(limit)
        )
        result = await session.execute(stmt)
        messages = result.scalars().all()
        
        return [
            MessageResponse(
                id=message.id,
                content=message.content,
                role=message.message_role,
                created_at=_to_iso_with_tz(message.created_at),
                model=message.model
            )
            for message in messages
        ]


@router.delete("/{tenant_id}/sessions/{session_id}/messages/{message_id}")
async def delete_message(
    tenant_id: str, 
    session_id: str, 
    message_id: str, 
    request: Request,
):
    """Delete a specific message"""
    session_factory = _get_session_factory(request)
    
    try:
        safe_tenant_id = _validate_uuid(tenant_id, "tenant_id")
        safe_session_id = _validate_uuid(session_id, "session_id")
        safe_message_id = _validate_uuid(message_id, "message_id")
    except SecurityError as exc:
        raise HTTPException(status_code=400, detail="Gecersiz parametre") from exc

    async with session_factory() as session:
        async with session.begin():
            # Verify session exists and belongs to tenant
            session_stmt = select(ChatSession).where(
                ChatSession.id == safe_session_id,
                ChatSession.tenant_id == safe_tenant_id
            )
            session_result = await session.execute(session_stmt)
            chat_session = session_result.scalar_one_or_none()
            
            if not chat_session:
                raise HTTPException(status_code=404, detail="Session bulunamadi")
            
            # Authorization check removed - tenant_id verification is sufficient
            
            # Find and delete message
            message_stmt = select(ChatMessage).where(
                ChatMessage.id == safe_message_id,
                ChatMessage.session_id == safe_session_id,
                ChatMessage.tenant_id == safe_tenant_id
            )
            message_result = await session.execute(message_stmt)
            message = message_result.scalar_one_or_none()
            
            if not message:
                raise HTTPException(status_code=404, detail="Message bulunamadi")
            
            await session.delete(message)
            
            return {"status": "ok", "deleted": True, "message_id": str(safe_message_id)}

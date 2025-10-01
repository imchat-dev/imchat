# app/api/routes/tenants.py
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import select, insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import sanitize_identifier, SecurityError
from app.models.db_models import Base, Tenant
from app.models.schemas import TenantCreateRequest, TenantResponse

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


@router.post("/", response_model=TenantResponse)
async def create_tenant(request: Request, payload: TenantCreateRequest):
    """Create a new tenant"""
    session_factory = _get_session_factory(request)
    
    try:
        safe_name = sanitize_identifier(payload.name, label="tenant_name")
    except SecurityError as exc:
        raise HTTPException(status_code=400, detail="Gecersiz tenant adi") from exc

    async with session_factory() as session:
        async with session.begin():
            try:
                # Create tenant record
                tenant_id = uuid.uuid4()
                created_at = datetime.now(timezone.utc)
                
                new_tenant = Tenant(
                    id=tenant_id,
                    name=safe_name,
                    description=payload.description,
                    created_at=created_at
                )
                session.add(new_tenant)
                await session.flush()
                
                return TenantResponse(
                    id=tenant_id,
                    name=safe_name,
                    description=payload.description,
                    created_at=created_at.isoformat()
                )
            except IntegrityError as exc:
                if "unique" in str(exc).lower() or "duplicate" in str(exc).lower():
                    raise HTTPException(status_code=409, detail="Bu tenant adi zaten kullaniliyor") from exc
                raise HTTPException(status_code=400, detail="Tenant olusturulamadi") from exc


@router.get("/{tenant_id}", response_model=TenantResponse)
async def get_tenant(tenant_id: str, request: Request):
    """Get tenant information"""
    session_factory = _get_session_factory(request)
    
    try:
        safe_tenant_id = uuid.UUID(tenant_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Gecersiz tenant ID format")

    async with session_factory() as session:
        stmt = select(Tenant).where(Tenant.id == safe_tenant_id)
        result = await session.execute(stmt)
        tenant = result.scalar_one_or_none()
        
        if not tenant:
            raise HTTPException(status_code=404, detail="Tenant bulunamadi")
            
        return TenantResponse(
            id=tenant.id,
            name=tenant.name,
            description=tenant.description,
            created_at=_to_iso_with_tz(tenant.created_at)
        )


@router.get("/list", response_model=List[TenantResponse])
async def list_tenants(request: Request, limit: int = 100, offset: int = 0):
    """List all tenants"""
    session_factory = _get_session_factory(request)
    
    async with session_factory() as session:
        stmt = select(Tenant).offset(offset).limit(limit)
        result = await session.execute(stmt)
        tenants = result.scalars().all()
        
        return [
            TenantResponse(
                id=tenant.id,
                name=tenant.name,
                description=tenant.description,
                created_at=_to_iso_with_tz(tenant.created_at)
            )
            for tenant in tenants
        ]


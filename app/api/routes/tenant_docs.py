# app/api/routes/tenant_docs.py
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Request, Query
from sqlalchemy import select, insert, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import sanitize_identifier, SecurityError
from app.models.db_models import Base, Tenant, Document
from app.models.schemas import DocumentUploadRequest, DocumentResponse

router = APIRouter(prefix="/tenants")


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


@router.post("/{tenant_id}/docs", response_model=DocumentResponse, status_code=201)
async def upload_document(tenant_id: uuid.UUID, request: Request, payload: DocumentUploadRequest):
    """Upload a document for a tenant"""
    session_factory = _get_session_factory(request)
    
    safe_tenant_id = tenant_id

    async with session_factory() as session:
        async with session.begin():
            # Verify tenant exists FIRST before sanitizing inputs
            tenant_stmt = select(Tenant).where(Tenant.id == safe_tenant_id)
            tenant_result = await session.execute(tenant_stmt)
            tenant = tenant_result.scalar_one_or_none()
            
            if not tenant:
                raise HTTPException(status_code=404, detail="Tenant bulunamadi")
            
            # Now sanitize inputs after tenant check
            try:
                safe_name = sanitize_identifier(payload.name, label="document_name")
                safe_filepath = sanitize_identifier(payload.filepath, label="filepath")
                safe_ext = sanitize_identifier(payload.ext, label="extension")
            except SecurityError as exc:
                raise HTTPException(status_code=400, detail="Gecersiz parametre") from exc
            
            # Create document record
            doc_id = uuid.uuid4()
            created_at = datetime.now(timezone.utc)
            
            new_document = Document(
                id=doc_id,
                tenant_id=safe_tenant_id,
                filepath=safe_filepath,
                name=safe_name,
                ext=safe_ext,
                created_at=created_at
            )
            session.add(new_document)
            await session.flush()
            
            return DocumentResponse(
                id=doc_id,
                name=safe_name,
                filepath=safe_filepath,
                ext=safe_ext,
                created_at=created_at.isoformat()
            )


@router.get("/{tenant_id}/docs", response_model=List[DocumentResponse])
async def get_documents(
    tenant_id: uuid.UUID, 
    request: Request,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0)
):
    """Get documents for a tenant"""
    session_factory = _get_session_factory(request)
    
    try:
        safe_tenant_id = tenant_id
    except SecurityError as exc:
        raise HTTPException(status_code=400, detail="Gecersiz parametre") from exc

    async with session_factory() as session:
        # Verify tenant exists
        tenant_stmt = select(Tenant).where(Tenant.id == safe_tenant_id)
        tenant_result = await session.execute(tenant_stmt)
        tenant = tenant_result.scalar_one_or_none()
        
        if not tenant:
            raise HTTPException(status_code=404, detail="Tenant bulunamadi")
        
        # Get documents
        stmt = (
            select(Document)
            .where(Document.tenant_id == safe_tenant_id)
            .order_by(Document.created_at.desc())  # Add ordering
            .offset(offset)
            .limit(limit)
        )
        result = await session.execute(stmt)
        documents = result.scalars().all()
        
        return [
            DocumentResponse(
                id=doc.id,
                name=doc.name,
                filepath=doc.filepath,
                ext=doc.ext,
                created_at=_to_iso_with_tz(doc.created_at)
            )
            for doc in documents
        ]


@router.get("/{tenant_id}/docs/{doc_id}", response_model=DocumentResponse)
async def get_document(tenant_id: uuid.UUID, doc_id: str, request: Request):
    """Get a specific document"""
    session_factory = _get_session_factory(request)
    
    try:
        safe_tenant_id = tenant_id
        safe_doc_id = _validate_uuid(doc_id, "doc_id")
    except SecurityError as exc:
        raise HTTPException(status_code=400, detail="Gecersiz parametre") from exc

    async with session_factory() as session:
        stmt = select(Document).where(
            Document.id == safe_doc_id,
            Document.tenant_id == safe_tenant_id
        )
        result = await session.execute(stmt)
        document = result.scalar_one_or_none()
        
        if not document:
            raise HTTPException(status_code=404, detail="Document bulunamadi")
            
        return DocumentResponse(
            id=document.id,
            name=document.name,
            filepath=document.filepath,
            ext=document.ext,
            created_at=_to_iso_with_tz(document.created_at)
        )


@router.delete("/{tenant_id}/docs/{doc_id}")
async def delete_document(tenant_id: uuid.UUID, doc_id: str, request: Request):
    """Delete a document"""
    session_factory = _get_session_factory(request)
    
    try:
        safe_tenant_id = tenant_id
        safe_doc_id = _validate_uuid(doc_id, "doc_id")
    except SecurityError as exc:
        raise HTTPException(status_code=400, detail="Gecersiz parametre") from exc

    async with session_factory() as session:
        async with session.begin():
            # Find and delete document
            stmt = select(Document).where(
                Document.id == safe_doc_id,
                Document.tenant_id == safe_tenant_id
            )
            result = await session.execute(stmt)
            document = result.scalar_one_or_none()
            
            if not document:
                raise HTTPException(status_code=404, detail="Document bulunamadi")
            
            await session.delete(document)
            
            return {"status": "ok", "deleted": True, "doc_id": str(safe_doc_id)}

# app/api/routes/chat.py
from fastapi import APIRouter, HTTPException, Request

from app.core.config import settings
from app.core.security import sanitize_identifier, SecurityError
from app.models.schemas import ChatRequest, ChatResponse
from app.services.chat_service import ChatService

router = APIRouter()


@router.post("/{tenant}", response_model=ChatResponse)
async def chat_endpoint(tenant: str, request: Request, payload: ChatRequest):
    session_factory = getattr(request.app.state, "db_sessionmaker", None)
    if session_factory is None:
        raise HTTPException(status_code=503, detail="Veritabani hazir degil")

    tenant_ids = getattr(request.app.state, "tenant_ids", None)
    if tenant_ids is None:
        raise HTTPException(status_code=503, detail="Tenant listesi bulunamadi")

    try:
        safe_tenant = sanitize_identifier(tenant, label="tenant")
    except SecurityError as exc:
        raise HTTPException(status_code=400, detail="Gecersiz tenant") from exc

    # Use tenant from URL path, fallback to payload or header
    tenant_id = safe_tenant or payload.tenant_id or request.headers.get("x-tenant-id") or settings.default_tenant_id
    
    # Check if tenant exists
    if tenant_id not in tenant_ids:
        raise HTTPException(status_code=404, detail="Tenant bulunamadi")

    vector = getattr(request.app.state, "vectorstore", None)
    llm = getattr(request.app.state, "llm", None)

    service = ChatService(
        session_factory=session_factory,
        tenant_ids=tenant_ids,
        vector=vector,
        llm=llm,
        tool_manager=None,  # Tool system disabled
    )
    return await service.handle_chat(
        request=request,
        payload=payload,
        tenant_id=tenant_id,
    )

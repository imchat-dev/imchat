# app/api/routes/chat.py
from fastapi import APIRouter, HTTPException, Request

from app.core.config import settings
from app.core.security import sanitize_identifier, SecurityError
from app.models.schemas import ChatRequest, ChatResponse
from app.services.chat_service import ChatService
from app.services.tool_service import ToolManager

router = APIRouter()


@router.post("/{profile_key}", response_model=ChatResponse)
async def chat_endpoint(profile_key: str, request: Request, payload: ChatRequest):
    session_factory = getattr(request.app.state, "db_sessionmaker", None)
    if session_factory is None:
        raise HTTPException(status_code=503, detail="Veritabani hazir degil")

    registry = getattr(request.app.state, "tenant_registry", None)
    if registry is None:
        raise HTTPException(status_code=503, detail="Tenant konfigurasyonu bulunamadi")

    try:
        safe_profile_key = sanitize_identifier(profile_key, label="profile_key")
    except SecurityError as exc:
        raise HTTPException(status_code=400, detail="Gecersiz profil") from exc

    tenant_id = payload.tenant_id or request.headers.get("x-tenant-id") or settings.default_tenant_id
    try:
        profile_config = registry.get_profile(tenant_id, safe_profile_key)
    except KeyError:
        raise HTTPException(status_code=404, detail="Profil bulunamadi")

    vector = getattr(request.app.state, "vectorstore", None)
    llm = getattr(request.app.state, "llm", None)

    service = ChatService(
        session_factory=session_factory,
        tenant_registry=registry,
        vector=vector,
        llm=llm,
        tool_manager=ToolManager(),
    )
    return await service.handle_chat(
        request=request,
        payload=payload,
        tenant_id=tenant_id,
        profile_key=safe_profile_key,
        profile_config=profile_config,
    )

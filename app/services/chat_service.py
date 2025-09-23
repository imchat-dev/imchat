﻿# app/services/chat_service.py
from __future__ import annotations

import logging
import math
import time
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import settings
from app.core.rate_limit import RateLimitError
from app.core.security import (
    SecurityError,
    ensure_safe_prompt,
    sanitize_identifier,
    sanitize_metadata,
)
from app.core.tenant_config import ProfileConfig, TenantConfigRegistry
from app.models.schemas import ChatRequest, ChatResponse
from app.repositories.chat_repo import ChatRepo
from app.repositories.session_repo import SessionRepo
from app.services.memory_service import MemoryService
from app.services.rag_service import RagService
from app.services.title_service import TitleService
from app.services.tool_service import ToolManager

logger = logging.getLogger(__name__)


class ChatService:
    """High level coordinator for the chat flow."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        tenant_registry: TenantConfigRegistry,
        vector=None,
        llm=None,
    ) -> None:
        self.session_factory = session_factory
        self.tenant_registry = tenant_registry
        self.tool_manager = ToolManager()
        self.rag = RagService(
            session_factory,
            vector=vector,
            llm=llm,
            tool_manager=self.tool_manager,
        )
        self.memory = MemoryService(session_factory)
        self.title = TitleService(session_factory)
        self.chat_repo = ChatRepo()
        self.session_repo = SessionRepo()

    async def handle_chat(
        self,
        request: Request,
        payload: ChatRequest,
        tenant_id: str,
        profile_key: str,
        profile_config: ProfileConfig,
    ) -> ChatResponse:
        if not payload.user_id or not (payload.question or "").strip():
            raise HTTPException(status_code=400, detail="user_id ve question zorunludur")

        try:
            safe_profile_key = sanitize_identifier(profile_key, label="profile_key")
        except SecurityError as exc:
            raise HTTPException(status_code=400, detail="Gecersiz profil") from exc

        try:
            safe_user_id = sanitize_identifier(str(payload.user_id), label="user_id")
            safe_question = ensure_safe_prompt(
                payload.question,
                max_length=settings.max_user_prompt_length,
            )
            safe_tenant_id = sanitize_identifier(str(tenant_id), label="tenant_id")
            safe_request_id = (
                sanitize_identifier(str(payload.request_id), label="request_id")
                if payload.request_id
                else str(uuid.uuid4())
            )
        except SecurityError as exc:
            logger.warning("Blocked unsafe chat payload: %s", exc)
            raise HTTPException(
                status_code=400,
                detail="Guvenlik kontrolleri istegi reddetti.",
            ) from exc

        try:
            profile_config = self.tenant_registry.get_profile(safe_tenant_id, safe_profile_key)
        except KeyError:
            raise HTTPException(status_code=404, detail="Profil bulunamadi")

        payload = payload.copy(
            update={
                "question": safe_question,
                "user_id": safe_user_id,
                "tenant_id": safe_tenant_id,
                "request_id": safe_request_id,
            }
        )

        xff = request.headers.get("x-forwarded-for", "")
        forwarded_ip = xff.split(",")[0].strip() if xff else None
        raw_ip = forwarded_ip or (request.client.host if request.client else None)
        client_ip = sanitize_metadata(raw_ip, fallback="0.0.0.0", max_length=64)
        user_agent = sanitize_metadata(request.headers.get("user-agent"), fallback="-", max_length=200)

        limiter = getattr(request.app.state, "rate_limiter", None)
        if limiter:
            limiter_key = f"{safe_tenant_id}:{safe_profile_key}:{payload.user_id}:{client_ip}"
            try:
                await limiter.check(limiter_key)
            except RateLimitError as exc:
                retry_after = exc.retry_after or settings.rate_limit_window_seconds
                retry_after = max(1, int(math.ceil(retry_after)))
                raise HTTPException(
                    status_code=429,
                    detail="Cok fazla istek. Lutfen daha sonra tekrar deneyin.",
                    headers={"Retry-After": str(retry_after)},
                ) from exc

        request_id = payload.request_id or str(uuid.uuid4())

        async with self.session_factory() as session:
            async with session.begin():
                session_id = await self.session_repo.ensure_session(
                    session=session,
                    req=payload,
                    tenant_id=safe_tenant_id,
                    profile_key=safe_profile_key,
                    client_ip=client_ip,
                    user_agent=user_agent,
                )
                await self.chat_repo.insert_message(
                    session=session,
                    tenant_id=safe_tenant_id,
                    profile_key=safe_profile_key,
                    session_id=session_id,
                    role="user",
                    content=payload.question,
                    model=None,
                    latency_ms=None,
                    usage=None,
                )

        t0 = time.perf_counter()
        memory_text = await self._safe_memory(
            tenant_id=safe_tenant_id,
            session_id=session_id,
            profile_key=safe_profile_key,
            profile_config=profile_config,
        )
        answer = await self.rag.answer(
            question=payload.question,
            tenant_id=safe_tenant_id,
            profile_key=safe_profile_key,
            profile_config=profile_config,
            memory_text=memory_text,
        )
        latency_ms = int((time.perf_counter() - t0) * 1000)

        async with self.session_factory() as session:
            async with session.begin():
                msg_id = await self.chat_repo.insert_message(
                    session=session,
                    tenant_id=safe_tenant_id,
                    profile_key=safe_profile_key,
                    session_id=session_id,
                    role="assistant",
                    content=answer,
                    model=settings.llm_model,
                    latency_ms=latency_ms,
                    usage=None,
                )

                await self.chat_repo.insert_history(
                    session=session,
                    tenant_id=safe_tenant_id,
                    profile_key=safe_profile_key,
                    session_id=session_id,
                    req=payload,
                    answer=answer,
                    request_id=request_id,
                    client_ip=client_ip,
                    user_agent=user_agent,
                    latency_ms=latency_ms,
                    usage=None,
                )

                await self.title.maybe_set_session_title(
                    session=session,
                    tenant_id=safe_tenant_id,
                    profile_key=safe_profile_key,
                    session_id=session_id,
                    first_question=payload.question,
                )

        return ChatResponse(
            answer=answer,
            profile_key=safe_profile_key,
            session_id=session_id,
            session_title=self._fallback_title(payload.question),
            last_activity=self._utcnow_iso(),
            preview=self._make_preview(answer),
            message_id=msg_id,
        )

    async def _safe_memory(
        self,
        tenant_id: str,
        session_id: Optional[str],
        profile_key: str,
        profile_config: ProfileConfig,
    ) -> str:
        if not session_id:
            return ""
        try:
            return await self.memory.build_memory(
                tenant_id=tenant_id,
                session_id=session_id,
                profile_key=profile_key,
                profile_config=profile_config,
            )
        except Exception as exc:  # pragma: no cover
            logger.warning("memory build failed: %s", exc)
            return ""

    def _utcnow_iso(self) -> str:
        dt = datetime.now(timezone.utc)
        return dt.isoformat()

    def _fallback_title(self, first_question: str) -> str:
        first_line = (first_question or "").strip().splitlines()[0][:60]
        return self._sanitize_title(first_line or "Sohbet")

    def _make_preview(self, text: str, limit: int = 100) -> str:
        cleaned = self._strip_md_html(text or "")
        if len(cleaned) <= limit:
            return cleaned
        cut = cleaned.rfind(" ", 0, limit)
        return (cleaned[:cut].rstrip() if cut > 40 else cleaned[:limit].rstrip()) + "..."

    def _strip_md_html(self, value: str) -> str:
        import re

        cleaned = re.sub(r"<[^>]+>", " ", value or "")
        cleaned = re.sub(r"`{1,3}.*?`{1,3}", " ", cleaned)
        cleaned = re.sub(r"\*\*|__", "", cleaned)
        cleaned = re.sub(r"[_*~>#-]+", " ", cleaned)
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        return cleaned

    def _sanitize_title(self, value: str) -> str:
        sanitized = (value or "").strip()
        sanitized = sanitized.replace("\n", " ").replace('"', "").replace("'", "")
        while sanitized and sanitized[-1] in ".!?":
            sanitized = sanitized[:-1]
        if len(sanitized) > 80:
            sanitized = sanitized[:80].rstrip()
        return sanitized

# app/repositories/chat_repo.py
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Dict, Optional

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import sanitize_text
from app.models.db_models import ChatHistory, ChatMessage, ChatSession


class ChatRepo:
    async def insert_message(
        self,
        session: AsyncSession,
        tenant_id: str,
        session_id: str,
        role: str,
        content: str,
        model: Optional[str] = None,
        latency_ms: Optional[int] = None,
        usage: Optional[Dict] = None,
    ) -> str:
        prompt_t = (usage or {}).get("prompt_tokens") or 0
        completion_t = (usage or {}).get("completion_tokens") or 0
        total_t = (usage or {}).get("total_tokens") or 0

        safe_content = sanitize_text(content, max_length=settings.max_user_prompt_length)
        session_uuid = uuid.UUID(session_id)

        message = ChatMessage(
            tenant_id=tenant_id,
            session_id=session_uuid,
            message_role=role,
            content=safe_content,
            model=model,
            latency_ms=latency_ms or 0,
            prompt_tokens=prompt_t,
            completion_tokens=completion_t,
            total_tokens=total_t,
        )
        session.add(message)
        await session.flush()

        await session.execute(
            update(ChatSession)
            .where(
                ChatSession.id == session_uuid,
                ChatSession.tenant_id == tenant_id,
            )
            .values(last_activity_at=datetime.now(timezone.utc))
        )

        return str(message.id)

    async def insert_history(
        self,
        session: AsyncSession,
        tenant_id: str,
        session_id: str,
        req,
        answer: str,
        request_id: str,
        client_ip: Optional[str],
        user_agent: Optional[str],
        latency_ms: Optional[int],
        usage: Optional[Dict],
    ) -> None:
        prompt_t = (usage or {}).get("prompt_tokens") or 0
        completion_t = (usage or {}).get("completion_tokens") or 0
        total_t = (usage or {}).get("total_tokens") or 0

        ip_val = client_ip or "0.0.0.0"
        ua_val = user_agent or "-"
        question = sanitize_text(req.question, max_length=settings.max_user_prompt_length)
        safe_answer = sanitize_text(answer, max_length=settings.max_user_prompt_length)

        history_row = ChatHistory(
            tenant_id=tenant_id,
            session_id=uuid.UUID(session_id),
            request_id=request_id,
            ip=ip_val,
            user_agent=ua_val,
            model=settings.llm_model,
            question=question,
            answer=safe_answer,
            latency_ms=latency_ms or 0,
            prompt_tokens=prompt_t,
            completion_tokens=completion_t,
            total_tokens=total_t,
        )
        session.add(history_row)

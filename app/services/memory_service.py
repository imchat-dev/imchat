# app/services/memory_service.py
from __future__ import annotations

import logging
import uuid
from typing import Dict, List

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.adapters.llm.openai_provider import get_chat_llm
from app.core.config import settings
from app.models.db_models import ChatMessage

logger = logging.getLogger(__name__)


class MemoryService:
    """Build short-lived conversation memory using conversation history."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]):
        self.session_factory = session_factory

    async def build_memory(
        self,
        tenant_id: str,
        session_id: str,
    ) -> str:
        try:
            history = await self._get_conversation_history(tenant_id, session_id, limit=20)
            if not history:
                return ""

            summary = await self._summarize(history)
            recent = self._format_recent(history, limit=4)
            return (summary + recent).strip()
        except Exception as exc:  # pragma: no cover
            logger.warning("memory build error: %s", exc)
            return ""

    async def _get_conversation_history(
        self,
        tenant_id: str,
        session_id: str,
        limit: int = 20,
    ) -> List[Dict]:
        session_uuid = uuid.UUID(session_id)
        stmt = (
            select(
                ChatMessage.message_role,
                ChatMessage.content,
                ChatMessage.created_at,
            )
            .where(
                ChatMessage.session_id == session_uuid,
                ChatMessage.tenant_id == tenant_id,
                ChatMessage.message_role.in_(["user", "assistant"]),
            )
            .order_by(ChatMessage.created_at.asc())
            .limit(limit)
        )

        async with self.session_factory() as session:
            result = await session.execute(stmt)
            rows = result.all()

        return [
            {
                "role": row.message_role,
                "content": row.content,
                "timestamp": row.created_at,
            }
            for row in rows
        ]

    async def _summarize(self, history: List[Dict]) -> str:
        if len(history) < 4:
            return ""
        try:
            llm = get_chat_llm(temperature=0.1, model=settings.llm_model_mini)
            conversation_text = ""
            for msg in history[:-2]:
                role_label = "Kullanici" if msg["role"] == "user" else "Asistan"
                conversation_text += f"{role_label}: {msg['content']}\n\n"

            summary_context = "kullanici"
            prompt = (
                "Bu {role} sohbetinin onemli noktalarini kisaca ozetle.\n\n"
                "Kurallar:\n"
                "- En fazla 3-4 cumle kullan\n"
                "- Sadece onemli soru ve cevaplari belirt\n"
                "- Tekrar yok\n"
                "- Turkce yaz\n\n"
                "Sohbet:\n{history}\n\nOzet:"
            ).format(role=summary_context, history=conversation_text)

            resp = await llm.ainvoke(prompt)
            text = getattr(resp, "content", str(resp)).strip()
            return f"Onceki Konusma Ozeti: {text}\n\n" if text else ""
        except Exception as exc:  # pragma: no cover
            logger.warning("summary error: %s", exc)
            return ""

    def _format_recent(self, history: List[Dict], limit: int = 4) -> str:
        if not history:
            return ""
        recent = history[-limit:]
        lines = []
        for msg in recent:
            role_label = "Kullanici" if msg["role"] == "user" else "Asistan"
            lines.append(f"{role_label}: {msg['content']}")
        return "Son Mesajlar:\n" + "\n".join(lines) + "\n\n"

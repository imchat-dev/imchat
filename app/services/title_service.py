# app/services/title_service.py
from __future__ import annotations

import asyncio
import logging
import uuid

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.adapters.llm.openai_provider import get_chat_llm
from app.models.db_models import ChatSession

logger = logging.getLogger(__name__)


class TitleService:
    """Improve chat session titles based on the initial question."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]):
        self.session_factory = session_factory

    async def maybe_set_session_title(
        self,
        session: AsyncSession,
        tenant_id: str,
        profile_key: str,
        session_id: str,
        first_question: str,
    ) -> None:
        session_uuid = uuid.UUID(session_id)
        result = await session.execute(
            select(ChatSession.title, ChatSession.title_locked)
            .where(
                ChatSession.id == session_uuid,
                ChatSession.tenant_id == tenant_id,
                ChatSession.profile_key == profile_key,
            )
        )
        row = result.one_or_none()
        if not row:
            return
        if row.title and bool(row.title_locked):
            return

        fallback = self._sanitize(first_question[:60] if first_question else "Sohbet")
        await session.execute(
            update(ChatSession)
            .where(
                ChatSession.id == session_uuid,
                ChatSession.tenant_id == tenant_id,
                ChatSession.profile_key == profile_key,
                ChatSession.title.is_(None),
            )
            .values(title=fallback)
        )

        asyncio.create_task(
            self._upgrade_title_async(tenant_id, profile_key, session_id, first_question)
        )

    async def _upgrade_title_async(
        self,
        tenant_id: str,
        profile_key: str,
        session_id: str,
        first_question: str,
    ) -> None:
        try:
            llm = get_chat_llm(temperature=0.1)
            prompt = (
                "Profil: {profile}\n"
                "Kullanicinin ilk mesajina gore tek satir kisa bir sohbet basligi uret.\n"
                "- Turkce\n- 4-6 kelime\n- Ozel karakter yok\n- Bas harfler buyuk\n- Sonda nokta yok\n"
                "Sadece basligi yaz.\n\n"
                "Ilk mesaj: {q}"
            ).format(profile=profile_key, q=first_question)

            resp = await llm.ainvoke(prompt)
            better = getattr(resp, "content", str(resp)).strip()
            title = self._sanitize(better) or self._sanitize(first_question[:60] if first_question else "Sohbet")

            async with self.session_factory() as session:
                async with session.begin():
                    await session.execute(
                        update(ChatSession)
                        .where(
                            ChatSession.id == uuid.UUID(session_id),
                            ChatSession.tenant_id == tenant_id,
                            ChatSession.profile_key == profile_key,
                        )
                        .values(title=title)
                    )
        except Exception as exc:  # pragma: no cover
            logger.warning("title upgrade failed for %s: %s", session_id, exc)

    def _sanitize(self, value: str) -> str:
        sanitized = (value or "").strip()
        sanitized = sanitized.replace("\n", " ").replace('"', "").replace("'", "")
        while sanitized and sanitized[-1] in ".!?":
            sanitized = sanitized[:-1]
        if len(sanitized) > 80:
            sanitized = sanitized[:80].rstrip()
        return sanitized

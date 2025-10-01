# app/repositories/feedback_repo.py
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.db_models import ChatFeedback, ChatMessage


class FeedbackRepo:
    async def message_exists(
        self,
        session: AsyncSession,
        message_id: str,
        tenant_id: uuid.UUID,
    ) -> bool:
        stmt = select(ChatMessage.id).where(
            ChatMessage.id == uuid.UUID(message_id),
            ChatMessage.tenant_id == str(tenant_id),
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none() is not None

    async def get_feedback_id_for_message(
        self,
        session: AsyncSession,
        message_id: str,
        tenant_id: uuid.UUID,
    ) -> str | None:
        stmt = select(ChatFeedback.id).where(
            ChatFeedback.message_id == uuid.UUID(message_id),
            ChatFeedback.tenant_id == str(tenant_id),
        )
        result = await session.execute(stmt)
        feedback_id = result.scalar_one_or_none()
        return str(feedback_id) if feedback_id else None

    async def insert_feedback(
        self,
        session: AsyncSession,
        tenant_id: uuid.UUID,
        message_id: str,
        score: int,
        reason: str,
    ) -> None:
        feedback = ChatFeedback(
            tenant_id=str(tenant_id),
            message_id=uuid.UUID(message_id),
            score=score,
            reason=reason,
        )
        session.add(feedback)

    async def update_feedback(
        self,
        session: AsyncSession,
        tenant_id: uuid.UUID,
        message_id: str,
        score: int,
        reason: str,
    ) -> None:
        await session.execute(
            update(ChatFeedback)
            .where(
                ChatFeedback.message_id == uuid.UUID(message_id),
                ChatFeedback.tenant_id == str(tenant_id),
            )
            .values(score=score, reason=reason, created_at=datetime.now(timezone.utc))
        )

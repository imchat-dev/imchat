# app/repositories/session_repo.py
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import sanitize_metadata
from app.models.db_models import ChatSession
from app.models.schemas import ChatRequest


class SessionRepo:
    async def ensure_session(
        self,
        session: AsyncSession,
        req: ChatRequest,
        tenant_id: uuid.UUID,
        client_ip: Optional[str],
        user_agent: Optional[str],
    ) -> str:
        """Create or update a chat session for the incoming request."""
        ip_val = sanitize_metadata(client_ip, fallback="0.0.0.0", max_length=64)
        ua_val = sanitize_metadata(user_agent, fallback="-", max_length=200)
        last_activity = datetime.now(timezone.utc)

        if req.session_id:
            session_uuid = uuid.UUID(str(req.session_id))
            stmt = (
                insert(ChatSession)
                .values(
                    id=session_uuid,
                    tenant_id=str(tenant_id),
                    client_ip=ip_val,
                    user_agent=ua_val,
                    last_activity_at=last_activity,
                )
                .on_conflict_do_update(
                    index_elements=[ChatSession.id],
                    set_={
                        "tenant_id": str(tenant_id),
                        "last_activity_at": last_activity,
                        "client_ip": ip_val,
                        "user_agent": ua_val,
                    },
                )
                .returning(ChatSession.id)
            )
            result = await session.execute(stmt)
            return str(result.scalar_one())

        new_session = ChatSession(
            tenant_id=str(tenant_id),
            client_ip=ip_val,
            user_agent=ua_val,
            last_activity_at=last_activity,
        )
        session.add(new_session)
        await session.flush()
        return str(new_session.id)


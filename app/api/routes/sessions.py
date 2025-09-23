# app/api/routes/sessions.py
from __future__ import annotations

import math
import re
import uuid
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy import delete, func, select, update

from app.core.config import settings
from app.core.rate_limit import RateLimitError
from app.core.security import (
    SecurityError,
    sanitize_identifier,
    sanitize_text,
)
from app.models.db_models import ChatMessage, ChatSession
from app.models.schemas import FeedbackRequest
from app.repositories.feedback_repo import FeedbackRepo

router = APIRouter()


# ------------ Helpers ------------
async def _apply_rate_limit(request: Request, key: str) -> None:
    limiter = getattr(request.app.state, "rate_limiter", None)
    if not limiter:
        return
    try:
        await limiter.check(key)
    except RateLimitError as exc:
        retry_after = exc.retry_after or settings.rate_limit_window_seconds
        retry_after = max(1, int(math.ceil(retry_after)))
        raise HTTPException(
            status_code=429,
            detail="Cok fazla istek. Lutfen daha sonra tekrar deneyin.",
            headers={"Retry-After": str(retry_after)},
        ) from exc


def _to_iso_with_tz(dt) -> Optional[str]:
    if dt is None:
        return None
    try:
        from datetime import timezone

        if getattr(dt, "tzinfo", None) is None:
            return dt.replace(tzinfo=timezone.utc).astimezone(timezone.utc).isoformat()
        return dt.astimezone(timezone.utc).isoformat()
    except Exception:
        return str(dt)


def _make_preview(text: str, limit: int = 120) -> str:
    value = text or ""
    value = re.sub(r"<[^>]+>", " ", value)
    value = re.sub(r"`{1,3}.*?`{1,3}", " ", value)
    value = re.sub(r"\s+", " ", value).strip()
    if len(value) <= limit:
        return value
    cut = value.rfind(" ", 0, limit)
    return (value[:cut].rstrip() if cut > 40 else value[:limit].rstrip()) + "..."


def _sanitize_title_text(raw: str) -> str:
    title = sanitize_text(raw, max_length=120)
    title = title.replace("\n", " ").replace('"', "").replace("'", "")
    while title and title[-1] in ".!?":
        title = title[:-1]
    return title


def _get_session_factory(request: Request):
    session_factory = getattr(request.app.state, "db_sessionmaker", None)
    if session_factory is None:
        raise HTTPException(status_code=503, detail="Veritabani hazir degil")
    return session_factory


def _resolve_tenant_and_profile(
    request: Request,
    profile_key: str,
    tenant_id_param: Optional[str] = None,
):
    registry = getattr(request.app.state, "tenant_registry", None)
    if registry is None:
        raise HTTPException(status_code=503, detail="Tenant konfigurasyonu bulunamadi")

    tenant_id = (
        tenant_id_param
        or request.headers.get("x-tenant-id")
        or settings.default_tenant_id
    )
    try:
        safe_tenant_id = sanitize_identifier(tenant_id, label="tenant_id")
        safe_profile_key = sanitize_identifier(profile_key, label="profile_key")
    except SecurityError as exc:
        raise HTTPException(status_code=400, detail="Gecersiz tenant veya profil") from exc

    try:
        registry.get_profile(safe_tenant_id, safe_profile_key)
    except KeyError:
        raise HTTPException(status_code=404, detail="Profil bulunamadi")

    return safe_tenant_id, safe_profile_key


class TitleBody(BaseModel):
    title: str
    user_id: str


@router.get("/{profile_key}/messages")
async def get_chat_messages(
    profile_key: str,
    request: Request,
    user_id: str,
    session_id: Optional[str] = None,
    tenant_id: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=500),
):
    session_factory = _get_session_factory(request)
    tenant_id, profile_key = _resolve_tenant_and_profile(request, profile_key, tenant_id)

    try:
        safe_user_id = sanitize_identifier(user_id, label="user_id")
        safe_session_id = sanitize_identifier(session_id, label="session_id") if session_id else None
    except SecurityError as exc:
        raise HTTPException(status_code=400, detail="Gecersiz parametre") from exc

    await _apply_rate_limit(request, f"messages:{tenant_id}:{profile_key}:{safe_user_id}")

    async with session_factory() as session:
        sid = safe_session_id

        if not sid:
            latest_stmt = (
                select(ChatSession.id)
                .where(
                    ChatSession.tenant_id == tenant_id,
                    ChatSession.profile_key == profile_key,
                    ChatSession.user_id == safe_user_id,
                )
                .order_by(func.coalesce(ChatSession.last_activity_at, ChatSession.started_at).desc())
                .limit(1)
            )
            result = await session.execute(latest_stmt)
            latest = result.scalar_one_or_none()
            if latest is not None:
                sid = str(latest)

        if not sid:
            return {"session_id": None, "messages": []}

        session_uuid = uuid.UUID(sid)
        owner_stmt = select(ChatSession.user_id).where(
            ChatSession.id == session_uuid,
            ChatSession.tenant_id == tenant_id,
            ChatSession.profile_key == profile_key,
        )
        owner_result = await session.execute(owner_stmt)
        owner = owner_result.scalar_one_or_none()
        if owner is None or str(owner) != safe_user_id:
            return {"session_id": None, "messages": []}

        messages_stmt = (
            select(ChatMessage.message_role, ChatMessage.content, ChatMessage.created_at)
            .where(
                ChatMessage.session_id == session_uuid,
                ChatMessage.tenant_id == tenant_id,
                ChatMessage.profile_key == profile_key,
            )
            .order_by(ChatMessage.created_at.asc())
            .limit(int(limit))
        )
        result = await session.execute(messages_stmt)
        rows = result.all()

    messages = [
        {
            "message_role": row.message_role,
            "content": row.content,
            "created_at": _to_iso_with_tz(row.created_at),
        }
        for row in rows
    ]
    return {"session_id": sid, "messages": messages}


@router.get("/{profile_key}/sessions")
async def get_sessions(
    profile_key: str,
    request: Request,
    user_id: str,
    tenant_id: Optional[str] = Query(None),
    limit: int = Query(20, ge=1, le=100),
):
    session_factory = _get_session_factory(request)
    tenant_id, profile_key = _resolve_tenant_and_profile(request, profile_key, tenant_id)

    try:
        safe_user_id = sanitize_identifier(user_id, label="user_id")
    except SecurityError as exc:
        raise HTTPException(status_code=400, detail="Gecersiz parametre") from exc

    await _apply_rate_limit(request, f"sessions:{tenant_id}:{profile_key}:{safe_user_id}")

    last_role_subquery = (
        select(ChatMessage.message_role)
        .where(
            ChatMessage.session_id == ChatSession.id,
            ChatMessage.tenant_id == tenant_id,
            ChatMessage.profile_key == profile_key,
            ChatMessage.message_role.in_(["assistant", "user"]),
        )
        .order_by(ChatMessage.created_at.desc())
        .limit(1)
        .scalar_subquery()
    )

    last_content_subquery = (
        select(ChatMessage.content)
        .where(
            ChatMessage.session_id == ChatSession.id,
            ChatMessage.tenant_id == tenant_id,
            ChatMessage.profile_key == profile_key,
            ChatMessage.message_role.in_(["assistant", "user"]),
        )
        .order_by(ChatMessage.created_at.desc())
        .limit(1)
        .scalar_subquery()
    )

    stmt = (
        select(
            ChatSession.id,
            ChatSession.title,
            ChatSession.title_locked,
            ChatSession.started_at,
            ChatSession.last_activity_at,
            func.coalesce(ChatSession.last_activity_at, ChatSession.started_at).label("last_activity"),
            last_role_subquery.label("last_role"),
            last_content_subquery.label("last_content"),
        )
        .where(
            ChatSession.tenant_id == tenant_id,
            ChatSession.profile_key == profile_key,
            ChatSession.user_id == safe_user_id,
        )
        .order_by(func.coalesce(ChatSession.last_activity_at, ChatSession.started_at).desc())
        .limit(int(limit))
    )

    async with session_factory() as session:
        result = await session.execute(stmt)
        rows = result.all()

    sessions = [
        {
            "session_id": str(row.id),
            "title": row.title,
            "started_at": _to_iso_with_tz(row.started_at),
            "last_activity": _to_iso_with_tz(row.last_activity),
            "preview": _make_preview(row.last_content or ""),
            "title_locked": bool(row.title_locked),
        }
        for row in rows
    ]
    return sessions


@router.post("/{profile_key}/sessions/{session_id}/title")
async def set_title(
    profile_key: str,
    session_id: str,
    body: TitleBody,
    request: Request,
    tenant_id: Optional[str] = Query(None),
):
    session_factory = _get_session_factory(request)
    tenant_id, profile_key = _resolve_tenant_and_profile(request, profile_key, tenant_id)

    try:
        safe_session_id = sanitize_identifier(session_id, label="session_id")
        safe_user_id = sanitize_identifier(body.user_id, label="user_id")
    except SecurityError as exc:
        raise HTTPException(status_code=400, detail="Gecersiz parametre") from exc

    await _apply_rate_limit(request, f"title:{tenant_id}:{profile_key}:{safe_user_id}")

    async with session_factory() as session:
        async with session.begin():
            session_uuid = uuid.UUID(safe_session_id)
            owner_stmt = select(ChatSession.user_id).where(
                ChatSession.id == session_uuid,
                ChatSession.tenant_id == tenant_id,
                ChatSession.profile_key == profile_key,
            )
            owner_result = await session.execute(owner_stmt)
            owner = owner_result.scalar_one_or_none()
            if owner is None or str(owner) != safe_user_id:
                raise HTTPException(status_code=403, detail="Yetkisiz")

            title = _sanitize_title_text(body.title)
            await session.execute(
                update(ChatSession)
                .where(ChatSession.id == session_uuid)
                .values(title=title, title_locked=True)
            )

    return {"status": "ok", "title_locked": True}


@router.delete("/{profile_key}/sessions/{session_id}")
async def delete_session(
    profile_key: str,
    session_id: str,
    user_id: str,
    request: Request,
    tenant_id: Optional[str] = Query(None),
):
    session_factory = _get_session_factory(request)
    tenant_id, profile_key = _resolve_tenant_and_profile(request, profile_key, tenant_id)

    try:
        safe_session_id = sanitize_identifier(session_id, label="session_id")
        safe_user_id = sanitize_identifier(user_id, label="user_id")
    except SecurityError as exc:
        raise HTTPException(status_code=400, detail="Gecersiz parametre") from exc

    await _apply_rate_limit(request, f"delete:{tenant_id}:{profile_key}:{safe_user_id}")

    session_uuid = uuid.UUID(safe_session_id)

    async with session_factory() as session:
        async with session.begin():
            owner_stmt = select(ChatSession.user_id).where(
                ChatSession.id == session_uuid,
                ChatSession.tenant_id == tenant_id,
                ChatSession.profile_key == profile_key,
            )
            owner_result = await session.execute(owner_stmt)
            owner = owner_result.scalar_one_or_none()
            if owner is None or str(owner) != safe_user_id:
                raise HTTPException(status_code=403, detail="Yetkisiz")

            await session.execute(
                delete(ChatMessage).where(
                    ChatMessage.session_id == session_uuid,
                    ChatMessage.tenant_id == tenant_id,
                    ChatMessage.profile_key == profile_key,
                )
            )
            await session.execute(
                delete(ChatSession).where(
                    ChatSession.id == session_uuid,
                    ChatSession.tenant_id == tenant_id,
                    ChatSession.profile_key == profile_key,
                )
            )

    return {"status": "ok", "deleted": True, "session_id": safe_session_id}


@router.post("/{profile_key}/feedback")
async def submit_feedback(
    profile_key: str,
    request: Request,
    feedback: FeedbackRequest,
    tenant_id: Optional[str] = Query(None),
):
    session_factory = _get_session_factory(request)
    tenant_id, profile_key = _resolve_tenant_and_profile(request, profile_key, tenant_id)

    if not 1 <= feedback.score <= 5:
        raise HTTPException(status_code=400, detail="Score 1-5 araliginda olmalidir")

    try:
        safe_message_id = sanitize_identifier(feedback.message_id, label="message_id")
    except SecurityError as exc:
        raise HTTPException(status_code=400, detail="Gecersiz parametre") from exc

    await _apply_rate_limit(request, f"feedback:{tenant_id}:{profile_key}:{safe_message_id}")

    score_reasons = {
        1: "Rezalet",
        2: "Kotu",
        3: "Idare eder",
        4: "Iyi",
        5: "Cok iyi",
    }
    auto_reason = score_reasons.get(feedback.score, "Degerlendirme yok")

    repo = FeedbackRepo()

    async with session_factory() as session:
        async with session.begin():
            exists = await repo.message_exists(session, safe_message_id, tenant_id, profile_key)
            if not exists:
                raise HTTPException(status_code=404, detail="Mesaj bulunamadi")

            feedback_id = await repo.get_feedback_id_for_message(
                session,
                safe_message_id,
                tenant_id,
                profile_key,
            )
            if feedback_id:
                await repo.update_feedback(
                    session,
                    tenant_id,
                    profile_key,
                    safe_message_id,
                    feedback.score,
                    auto_reason,
                )
                return {
                    "status": "success",
                    "message": "Geri bildirim guncellendi",
                    "message_id": safe_message_id,
                    "score": feedback.score,
                }

            await repo.insert_feedback(
                session,
                tenant_id,
                profile_key,
                safe_message_id,
                feedback.score,
                auto_reason,
            )

    return {
        "status": "success",
        "message": "Geri bildirim kaydedildi",
        "message_id": safe_message_id,
        "score": feedback.score,
    }

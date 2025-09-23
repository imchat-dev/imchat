# app/models/schemas.py
from typing import Optional

from pydantic import BaseModel, ConfigDict


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str
    user_id: str
    tenant_id: Optional[str] = None
    session_id: Optional[str] = None
    request_id: Optional[str] = None


class ChatResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    answer: str
    status: str = "success"
    profile_key: Optional[str] = None
    session_id: Optional[str] = None
    session_title: Optional[str] = None
    last_activity: Optional[str] = None
    preview: Optional[str] = None
    message_id: Optional[str] = None


class FeedbackRequest(BaseModel):
    message_id: str
    score: int
    created_at: Optional[str] = None

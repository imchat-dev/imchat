# app/models/schemas.py
from typing import Optional, Literal
import uuid

from pydantic import BaseModel, ConfigDict, Field


class FileAttachment(BaseModel):
    name: str
    type: str
    encoding: str
    data: str


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str
    tenant_id: str
    session_id: Optional[str] = None
    request_id: Optional[str] = None


class ChatResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    answer: str
    files: Optional[FileAttachment] = None
    status: str = "success"
    tenant_id: Optional[str] = None
    session_id: Optional[str] = None
    session_title: Optional[str] = None
    last_activity: Optional[str] = None
    preview: Optional[str] = None
    message_id: Optional[str] = None


class FeedbackRequest(BaseModel):
    message_id: str
    score: int
    created_at: Optional[str] = None


# New schemas for tenant-based API
class TenantCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    
    name: str
    description: Optional[str] = None


class TenantResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    
    id: uuid.UUID
    name: str
    description: Optional[str] = None
    created_at: str


class SessionCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    
    title: Optional[str] = None


class SessionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    
    id: uuid.UUID
    title: Optional[str] = None
    started_at: str
    last_activity_at: Optional[str] = None


class MessageCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    
    content: str
    role: Literal["user", "assistant"] = "user"


class MessageResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    
    id: uuid.UUID
    content: str
    role: str
    created_at: str
    model: Optional[str] = None


class DocumentUploadRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    
    name: str
    filepath: str
    ext: str


class DocumentResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    
    id: uuid.UUID
    name: str
    filepath: str
    ext: str
    created_at: str

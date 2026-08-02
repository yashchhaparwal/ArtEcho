from typing import List, Optional, Any
from datetime import datetime
from pydantic import BaseModel
from app.models.session import SessionStatus
from app.schemas.artwork import ReferenceArtworkResponse
from app.schemas.message import MessageResponse


class SessionCreate(BaseModel):
    reference_artwork_ids: List[str]


class SessionReferenceResponse(BaseModel):
    id: str
    session_id: str
    reference_artwork_id: Optional[str] = None
    custom_image_url: Optional[str] = None
    is_custom_upload: bool
    reference_artwork: Optional[ReferenceArtworkResponse] = None
    created_at: datetime

    class Config:
        from_attributes = True


class SessionResponse(BaseModel):
    id: str
    user_id: str
    title: str
    status: SessionStatus
    context_summary: Optional[dict] = None
    is_ready_to_generate: bool = False
    is_saved: bool = False
    saved_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime
    session_references: List[SessionReferenceResponse] = []
    messages: List[MessageResponse] = []

    class Config:
        from_attributes = True


class SessionListResponse(BaseModel):
    sessions: List[SessionResponse]
    total: int

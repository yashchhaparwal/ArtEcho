from typing import List, Optional, Any
from datetime import datetime
from pydantic import BaseModel
from app.schemas.artwork import ReferenceArtworkResponse
from app.schemas.result import GeneratedArtworkResponse


class GalleryItemResponse(BaseModel):
    session_id: str
    title: str
    is_saved: bool
    saved_at: Optional[datetime] = None
    created_at: datetime
    reference_artwork: Optional[ReferenceArtworkResponse] = None
    latest_generated_artwork: Optional[GeneratedArtworkResponse] = None
    context_summary: Optional[dict] = None

    class Config:
        from_attributes = True


class GalleryListResponse(BaseModel):
    items: List[GalleryItemResponse]
    total: int

from typing import Any, Dict, Optional, List
from datetime import datetime
from pydantic import BaseModel


class ReferenceArtworkCreate(BaseModel):
    title: str
    artist: str
    year: Optional[str] = None
    movement_style: Optional[str] = None
    medium: Optional[str] = None
    description: Optional[str] = None
    source_attribution: Optional[str] = None
    image_url: str
    dominant_color: Optional[str] = None
    is_public_domain: bool = True


class ReferenceArtworkResponse(BaseModel):
    id: str
    title: str
    artist: str
    year: Optional[str] = None
    movement_style: Optional[str] = None
    medium: Optional[str] = None
    description: Optional[str] = None
    source_attribution: Optional[str] = None
    image_url: str
    dominant_color: Optional[str] = None
    is_public_domain: bool
    is_custom_upload: bool = False
    uploaded_by_user_id: Optional[str] = None
    visual_analysis: Optional[Dict[str, Any]] = None
    created_at: datetime

    class Config:
        from_attributes = True


class ArtworkListResponse(BaseModel):
    artworks: List[ReferenceArtworkResponse]
    total: int
    page: int
    page_size: int

from typing import List, Optional, Any
from datetime import datetime
from pydantic import BaseModel


class CritiqueSection(BaseModel):
    composition: Optional[str] = None
    color_theory: Optional[str] = None
    symbolism: Optional[str] = None
    emotional_impact: Optional[str] = None
    strengths: List[str] = []
    weaknesses: List[str] = []


class CritiqueResponse(BaseModel):
    id: str
    generated_artwork_id: str
    reference_critique: Optional[CritiqueSection] = None
    generated_critique: Optional[CritiqueSection] = None
    comparison: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True

    @classmethod
    def from_orm_model(cls, critique_orm: Any) -> "CritiqueResponse":
        ref = critique_orm.reference_critique
        gen = critique_orm.generated_critique
        return cls(
            id=critique_orm.id,
            generated_artwork_id=critique_orm.generated_artwork_id,
            reference_critique=CritiqueSection(**ref) if ref else None,
            generated_critique=CritiqueSection(**gen) if gen else None,
            comparison=critique_orm.comparison,
            created_at=critique_orm.created_at,
        )


class GeneratedArtworkResponse(BaseModel):
    id: str
    session_id: str
    image_url: str
    prompt_synthesized: str
    inspiration_level: str
    resolution: str
    model_provider: str
    generation_index: int
    created_at: datetime
    critique: Optional[CritiqueResponse] = None

    class Config:
        from_attributes = True


class SessionResultResponse(BaseModel):
    session_id: str
    session_title: str
    context_summary: Optional[dict] = None
    reference_artworks: List[Any] = []
    generated_artworks: List[GeneratedArtworkResponse] = []
    latest_generated: Optional[GeneratedArtworkResponse] = None
    is_ready_to_generate: bool

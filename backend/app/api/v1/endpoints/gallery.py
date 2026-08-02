from typing import Any, List
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_db, get_current_user
from app.models.user import User
from app.models.session import ChatSession, SessionReference
from app.models.generation import GeneratedArtwork, Critique
from app.schemas.gallery import GalleryItemResponse, GalleryListResponse
from app.schemas.artwork import ReferenceArtworkResponse
from app.schemas.result import GeneratedArtworkResponse, CritiqueResponse

router = APIRouter()


@router.get("", response_model=GalleryListResponse)
def get_gallery(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Any:
    """
    Get user's saved gallery sessions with reference artwork thumbnail and latest generated artwork.
    """
    saved_sessions = (
        db.query(ChatSession)
        .filter(ChatSession.user_id == current_user.id, ChatSession.is_saved == True)
        .order_by(ChatSession.saved_at.desc(), ChatSession.updated_at.desc())
        .all()
    )

    items = []
    for sess in saved_sessions:
        # Reference artwork
        ref = (
            db.query(SessionReference)
            .filter(SessionReference.session_id == sess.id)
            .first()
        )
        ref_artwork = ReferenceArtworkResponse.from_orm(ref.reference_artwork) if (ref and ref.reference_artwork) else None

        # Latest generated artwork
        gen = (
            db.query(GeneratedArtwork)
            .filter(GeneratedArtwork.session_id == sess.id)
            .order_by(GeneratedArtwork.generation_index.desc())
            .first()
        )
        gen_artwork = None
        if gen:
            crit_resp = CritiqueResponse.from_orm_model(gen.critique) if gen.critique else None
            gen_artwork = GeneratedArtworkResponse(
                id=gen.id,
                session_id=gen.session_id,
                image_url=gen.image_url,
                prompt_synthesized=gen.prompt_synthesized,
                inspiration_level=gen.inspiration_level,
                resolution=gen.resolution,
                model_provider=gen.model_provider,
                generation_index=gen.generation_index,
                created_at=gen.created_at,
                critique=crit_resp,
            )

        items.append(
            GalleryItemResponse(
                session_id=sess.id,
                title=sess.title,
                is_saved=sess.is_saved,
                saved_at=sess.saved_at,
                created_at=sess.created_at,
                reference_artwork=ref_artwork,
                latest_generated_artwork=gen_artwork,
                context_summary=sess.context_summary,
            )
        )

    return GalleryListResponse(
        items=items,
        total=len(items),
    )

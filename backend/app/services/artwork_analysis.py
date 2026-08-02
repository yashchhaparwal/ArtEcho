"""
artwork_analysis.py
===================
Ties the vision model to the database: analyse an artwork once, cache the
result on its row, and reuse it for every conversation that references it.

Vision inference is slow on CPU, so nothing here ever blocks a user-facing
request — callers schedule it as a FastAPI BackgroundTask, and the conversation
falls back to metadata-only if the analysis is not ready yet.
"""

import logging
from typing import Any, Dict, List, Optional

from app.db.session import SessionLocal
from app.models.artwork import ReferenceArtwork
from app.services.vision_provider import summarize_analysis, vision_service

logger = logging.getLogger(__name__)


def analyze_artwork_by_id(artwork_id: str, force: bool = False) -> Optional[Dict[str, Any]]:
    """
    Analyse one artwork and persist the result.

    Opens its own DB session because this runs after the response has been sent,
    by which point the request-scoped session is closed.
    """
    with SessionLocal() as db:
        artwork = db.query(ReferenceArtwork).filter(ReferenceArtwork.id == artwork_id).first()
        if not artwork:
            return None
        if artwork.visual_analysis and not force:
            return artwork.visual_analysis
        image_ref = artwork.image_url

    analysis = vision_service.analyze_artwork(image_ref)
    if not analysis:
        return None

    with SessionLocal() as db:
        artwork = db.query(ReferenceArtwork).filter(ReferenceArtwork.id == artwork_id).first()
        if artwork:
            artwork.visual_analysis = analysis
            db.commit()
            logger.info(f"Vision analysis stored for artwork {artwork_id} ('{artwork.title}')")
    return analysis


def analyze_artworks_by_ids(artwork_ids: List[str], force: bool = False) -> None:
    """Background-task entry point for a batch of artworks."""
    for artwork_id in artwork_ids:
        try:
            analyze_artwork_by_id(artwork_id, force=force)
        except Exception as exc:
            logger.warning(f"Vision analysis failed for artwork {artwork_id}: {exc}")


def build_artwork_meta(artwork: ReferenceArtwork) -> Dict[str, Any]:
    """
    Metadata block handed to the LLM for one reference artwork.

    `visual_summary` is what the vision model actually saw. For a user upload
    there is no title/artist/movement worth speaking of, so this is the only
    thing that lets the assistant ask pointed questions about the image.
    """
    return {
        "id": artwork.id,
        "title": artwork.title,
        "artist": artwork.artist,
        "year": artwork.year,
        "movement_style": artwork.movement_style,
        "medium": artwork.medium,
        "description": artwork.description,
        "image_url": artwork.image_url,
        "is_user_upload": bool(artwork.is_custom_upload),
        "visual_summary": summarize_analysis(artwork.visual_analysis),
    }

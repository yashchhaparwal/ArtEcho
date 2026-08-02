import logging
import random
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.deps import get_db, get_current_user
from app.models.user import User
from app.models.message import Message, MessageSender
from app.models.session import ChatSession, SessionReference
from app.models.generation import GeneratedArtwork, Critique
from app.schemas.result import (
    GeneratedArtworkResponse,
    CritiqueResponse,
    CritiqueSection,
    SessionResultResponse,
)
from app.schemas.artwork import ReferenceArtworkResponse
from app.services.prompt_builder import build_image_prompt, build_critique_user_message
from app.services.image_provider import image_service
from app.services.llm_provider import llm_service
from app.services.vision_provider import vision_service
from app.services.artwork_analysis import build_artwork_meta

logger = logging.getLogger(__name__)

router = APIRouter()


def _get_session_or_404(session_id: str, user_id: str, db: Session) -> ChatSession:
    sess = (
        db.query(ChatSession)
        .filter(ChatSession.id == session_id, ChatSession.user_id == user_id)
        .first()
    )
    if not sess:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")
    return sess


def _get_artwork_meta(sess: ChatSession, db: Session) -> list[dict]:
    refs = (
        db.query(SessionReference)
        .filter(SessionReference.session_id == sess.id)
        .all()
    )
    return [build_artwork_meta(r.reference_artwork) for r in refs if r.reference_artwork]


# ─────────────────────────────────────────────────────────────────────────────
# POST /sessions/{id}/generate
# ─────────────────────────────────────────────────────────────────────────────
@router.post("/{session_id}/generate", response_model=GeneratedArtworkResponse, status_code=status.HTTP_201_CREATED)
def generate_artwork(
    session_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    force: bool = Query(
        False,
        description="Generate now even if the assistant hasn't flagged the session as ready",
    ),
) -> Any:
    sess = _get_session_or_404(session_id, current_user.id, db)

    # The user decides when they've said enough, so `force` lets them generate
    # early. We still require at least one exchange, otherwise there is no
    # personal context to build a prompt from.
    if not sess.is_ready_to_generate and not force:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Session is not ready to generate. Complete the conversation first.",
        )

    if force and not sess.is_ready_to_generate:
        user_turns = (
            db.query(Message)
            .filter(Message.session_id == session_id, Message.sender == MessageSender.USER)
            .count()
        )
        if user_turns < 1:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Tell Muse at least one thing about what you want before generating.",
            )
        sess.is_ready_to_generate = True

    artwork_meta = _get_artwork_meta(sess, db)
    if not artwork_meta:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No reference artworks found for this session.",
        )

    # Build prompt
    prompt = build_image_prompt(sess.context_summary or {}, artwork_meta)
    logger.info(f"[generate] session={session_id} prompt={prompt[:120]}...")

    # Determine generation index up front — it also seeds the image model, so
    # pressing "Regenerate" on an unchanged prompt still yields a new artwork
    # instead of the provider's cached result for that prompt.
    existing_count = (
        db.query(GeneratedArtwork)
        .filter(GeneratedArtwork.session_id == session_id)
        .count()
    )

    result = image_service.generate(prompt, sess.context_summary, seed=random.randint(1, 2_000_000_000))

    if result.get("error"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=result["error"],
        )
    if result.get("warning"):
        logger.warning(f"[generate] session={session_id} {result['warning']}")

    inspiration = (sess.context_summary or {}).get("inspiration_level", "balanced")

    generated = GeneratedArtwork(
        session_id=session_id,
        image_url=result["image_url"],
        prompt_synthesized=prompt,
        inspiration_level=inspiration,
        resolution=result.get("resolution", "1024x1024"),
        model_provider=result["model_provider"],
        generation_index=existing_count + 1,
    )
    db.add(generated)
    db.commit()
    db.refresh(generated)
    return generated


# ─────────────────────────────────────────────────────────────────────────────
# POST /sessions/{id}/critique
# ─────────────────────────────────────────────────────────────────────────────
@router.post("/{session_id}/critique", response_model=CritiqueResponse, status_code=status.HTTP_201_CREATED)
def generate_critique(
    session_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Any:
    sess = _get_session_or_404(session_id, current_user.id, db)

    # Get most recent generated artwork
    generated = (
        db.query(GeneratedArtwork)
        .filter(GeneratedArtwork.session_id == session_id)
        .order_by(GeneratedArtwork.generation_index.desc())
        .first()
    )
    if not generated:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No generated artwork found. Call /generate first.",
        )

    # Return existing critique if it exists
    if generated.critique:
        return CritiqueResponse.from_orm_model(generated.critique)

    artwork_meta = _get_artwork_meta(sess, db)
    primary_meta = artwork_meta[0] if artwork_meta else {}

    # Look at the generated image before critiquing it. Without this the critic
    # only ever sees the prompt, so it describes what was *asked for* rather
    # than what the model actually produced.
    generated_visual = vision_service.describe_for_critique(generated.image_url)
    if not generated_visual:
        logger.info(
            f"[critique] session={session_id} no vision reading available; "
            f"critiquing from the prompt alone"
        )

    user_msg = build_critique_user_message(
        reference_artwork=primary_meta,
        generated_artwork_prompt=generated.prompt_synthesized,
        generated_artwork_url=generated.image_url,
        generated_visual_reading=generated_visual,
        additional_references=artwork_meta[1:],
    )

    # Call LLM via the shared provider service
    raw_output = _call_llm_for_critique(user_msg, primary_meta)

    # Parse structured output
    ref_raw = raw_output.get("reference_critique", {})
    gen_raw = raw_output.get("generated_critique", {})
    comparison = raw_output.get("comparison", "")

    critique = Critique(
        generated_artwork_id=generated.id,
        reference_critique=ref_raw,
        generated_critique=gen_raw,
        comparison=comparison,
    )
    db.add(critique)
    db.commit()
    db.refresh(critique)
    return CritiqueResponse.from_orm_model(critique)


def _call_llm_for_critique(user_message: str, primary_artwork_meta: dict) -> dict:
    """Invoke the shared LLM provider for structured critique output."""
    return llm_service.generate_critique(user_message, primary_artwork_meta)


# ─────────────────────────────────────────────────────────────────────────────
# GET /sessions/{id}/result
# ─────────────────────────────────────────────────────────────────────────────
@router.get("/{session_id}/result", response_model=SessionResultResponse)
def get_session_result(
    session_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Any:
    sess = _get_session_or_404(session_id, current_user.id, db)

    artwork_meta = _get_artwork_meta(sess, db)

    generated_artworks = (
        db.query(GeneratedArtwork)
        .filter(GeneratedArtwork.session_id == session_id)
        .order_by(GeneratedArtwork.generation_index.asc())
        .all()
    )

    generated_responses = []
    for g in generated_artworks:
        critique_resp = CritiqueResponse.from_orm_model(g.critique) if g.critique else None
        ga = GeneratedArtworkResponse(
            id=g.id,
            session_id=g.session_id,
            image_url=g.image_url,
            prompt_synthesized=g.prompt_synthesized,
            inspiration_level=g.inspiration_level,
            resolution=g.resolution,
            model_provider=g.model_provider,
            generation_index=g.generation_index,
            created_at=g.created_at,
            critique=critique_resp,
        )
        generated_responses.append(ga)

    latest = generated_responses[-1] if generated_responses else None

    return SessionResultResponse(
        session_id=sess.id,
        session_title=sess.title,
        context_summary=sess.context_summary,
        reference_artworks=artwork_meta,
        generated_artworks=generated_responses,
        latest_generated=latest,
        is_ready_to_generate=sess.is_ready_to_generate,
    )

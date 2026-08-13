import logging
import random
import time
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.orm import Session

from app.api.deps import get_db, get_current_user
from app.db.session import SessionLocal
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
from app.services.jobs import DONE, ERROR, job_registry
# Shared with the chat endpoint so both agree on which turns are still
# outstanding — see CONTEXT_EXTRACTION_EVERY_N_TURNS there.
from app.api.v1.endpoints.sessions import _unextracted_turn_count

logger = logging.getLogger(__name__)

router = APIRouter()

# How long `?wait=true` will block before handing back the job to poll. Kept
# under a typical proxy/browser idle timeout; the job keeps running regardless.
WAIT_TIMEOUT_SECONDS = 240.0
WAIT_POLL_INTERVAL = 0.25


def _trailing_exchanges(
    conversation: list[Message], count: int
) -> list[tuple[str, str]]:
    """
    The last `count` complete user→assistant exchanges, oldest first.

    Used to catch up the context summary at generation time when the
    conversation ended on a turn the batched extraction had not reached yet.
    """
    if count <= 0:
        return []

    exchanges: list[tuple[str, str]] = []
    pending_user: str | None = None
    for msg in conversation:
        if msg.sender == MessageSender.USER:
            pending_user = msg.content
        elif msg.sender == MessageSender.ASSISTANT and pending_user is not None:
            exchanges.append((pending_user, msg.content))
            pending_user = None
    # A final user turn with no reply yet still carries what they asked for.
    if pending_user is not None:
        exchanges.append((pending_user, ""))
    return exchanges[-count:]


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


def _serialize_generated(generated: GeneratedArtwork) -> dict:
    """Job results travel as plain JSON, so hand back the same shape the
    synchronous endpoint used to return."""
    return GeneratedArtworkResponse(
        id=generated.id,
        session_id=generated.session_id,
        image_url=generated.image_url,
        prompt_synthesized=generated.prompt_synthesized,
        inspiration_level=generated.inspiration_level,
        resolution=generated.resolution,
        model_provider=generated.model_provider,
        generation_index=generated.generation_index,
        created_at=generated.created_at,
        critique=CritiqueResponse.from_orm_model(generated.critique)
        if generated.critique
        else None,
    ).model_dump(mode="json")


def _await_job(job_id: str) -> dict:
    """
    Block until a job reaches a terminal state, then behave like the old
    synchronous endpoint. Only used by `?wait=true` callers (scripts and tests);
    the UI polls instead.
    """
    deadline = time.monotonic() + WAIT_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        job = job_registry.get(job_id)
        if job is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Job disappeared"
            )
        if job.status == DONE:
            return job.result or {}
        if job.status == ERROR:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=job.error
            )
        time.sleep(WAIT_POLL_INTERVAL)

    raise HTTPException(
        status_code=status.HTTP_504_GATEWAY_TIMEOUT,
        detail="Generation is taking longer than expected; poll the job instead.",
    )


# ─────────────────────────────────────────────────────────────────────────────
# GET /sessions/{id}/jobs/{job_id}
# ─────────────────────────────────────────────────────────────────────────────
@router.get("/{session_id}/jobs/{job_id}")
def get_job_status(
    session_id: str,
    job_id: str,
    current_user: User = Depends(get_current_user),
) -> Any:
    """
    Poll a long-running generation or critique.

    Deliberately touches no database at all — the client hits this every second
    or so while a 45-second image generation runs, and it would be perverse to
    reintroduce the connection pressure the job system exists to remove.
    """
    job = job_registry.get(job_id)
    if job is None or job.session_id != session_id or job.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    return job.to_dict()


# ─────────────────────────────────────────────────────────────────────────────
# POST /sessions/{id}/generate
# ─────────────────────────────────────────────────────────────────────────────
@router.post("/{session_id}/generate", status_code=status.HTTP_202_ACCEPTED)
def generate_artwork(
    session_id: str,
    response: Response,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    force: bool = Query(
        False,
        description="Generate now even if the assistant hasn't flagged the session as ready",
    ),
    wait: bool = Query(
        False,
        description="Block until the artwork is ready and return it, instead of returning a job to poll",
    ),
) -> Any:
    """
    Kick off an image generation.

    Returns `202` with a job to poll. Image generation against the free
    Pollinations tier measures ~45s cold, and blocking a request — and its
    pooled database connection — for that long is what made the rest of the app
    crawl. Pass `?wait=true` for the old blocking behaviour.
    """
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
        db.commit()

    artwork_meta = _get_artwork_meta(sess, db)
    if not artwork_meta:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No reference artworks found for this session.",
        )

    # Double-clicking the button shouldn't queue a second 45-second call.
    existing = job_registry.find_active("generate", session_id)
    if existing is not None:
        if wait:
            artwork = _await_job(existing.id)
            response.status_code = status.HTTP_201_CREATED
            return artwork
        return existing.to_dict()

    # Everything the worker needs is read here, while we still hold the request's
    # session, so the thread itself can run without a database connection.
    context_summary = dict(sess.context_summary or {})
    existing_count = (
        db.query(GeneratedArtwork)
        .filter(GeneratedArtwork.session_id == session_id)
        .count()
    )

    # Context extraction runs every other turn during the conversation. If the
    # user stopped on an unextracted turn, whatever they said last is not in the
    # summary yet — and the summary is exactly what the image prompt is built
    # from. Fold it in first, inside the job where the progress UI already
    # covers the wait.
    conversation = (
        db.query(Message)
        .filter(Message.session_id == session_id)
        .order_by(Message.created_at.asc())
        .all()
    )
    user_turns = sum(1 for m in conversation if m.sender == MessageSender.USER)
    pending_turns = _unextracted_turn_count(user_turns)
    pending_exchanges = _trailing_exchanges(conversation, pending_turns)

    def work(progress) -> dict:
        progress("Composing your prompt")

        summary = context_summary
        if pending_exchanges:
            try:
                delta = llm_service.extract_context_from_exchanges(
                    exchanges=pending_exchanges,
                    previous_context_summary=summary,
                )
                summary = llm_service._merge_context(summary, delta)
                with SessionLocal() as ctx_db:
                    row = (
                        ctx_db.query(ChatSession)
                        .filter(ChatSession.id == session_id)
                        .first()
                    )
                    if row is not None:
                        row.context_summary = summary
                        ctx_db.commit()
            except Exception as exc:
                logger.warning(
                    f"[generate] session={session_id} catch-up context extraction "
                    f"failed, using the stored summary: {exc}"
                )

        prompt = build_image_prompt(summary, artwork_meta)
        logger.info(f"[generate] session={session_id} prompt={prompt[:120]}...")
        seed = random.randint(1, 2_000_000_000)

        progress("Painting your artwork")
        result = image_service.generate(prompt, summary, seed=seed)

        if result.get("error"):
            raise RuntimeError(result["error"])
        if result.get("warning"):
            logger.warning(f"[generate] session={session_id} {result['warning']}")

        progress("Saving your artwork")
        # A fresh, short-lived session — the slow part is over by now.
        worker_db = SessionLocal()
        try:
            generated = GeneratedArtwork(
                session_id=session_id,
                image_url=result["image_url"],
                prompt_synthesized=prompt,
                inspiration_level=summary.get("inspiration_level", "balanced"),
                resolution=result.get("resolution", "1024x1024"),
                model_provider=result["model_provider"],
                generation_index=existing_count + 1,
            )
            worker_db.add(generated)
            worker_db.commit()
            worker_db.refresh(generated)
            payload = _serialize_generated(generated)
        finally:
            worker_db.close()

        if result.get("warning"):
            payload["warning"] = result["warning"]
        return payload

    job = job_registry.submit(
        kind="generate",
        session_id=session_id,
        user_id=current_user.id,
        work=work,
        initial_stage="Composing your prompt",
    )

    if wait:
        artwork = _await_job(job.id)
        response.status_code = status.HTTP_201_CREATED
        return artwork

    response.status_code = status.HTTP_202_ACCEPTED
    return job.to_dict()


# ─────────────────────────────────────────────────────────────────────────────
# POST /sessions/{id}/critique
# ─────────────────────────────────────────────────────────────────────────────
@router.post("/{session_id}/critique", status_code=status.HTTP_202_ACCEPTED)
def generate_critique(
    session_id: str,
    response: Response,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    wait: bool = Query(
        False,
        description="Block until the critique is ready and return it, instead of returning a job to poll",
    ),
) -> Any:
    """
    Kick off a critique of the latest generated artwork.

    This is the slowest operation in the app — a vision pass over the generated
    image, then a large structured document from the LLM in a single shot — so
    it runs as a job for the same reasons generation does.
    """
    sess = _get_session_or_404(session_id, current_user.id, db)

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

    # Already critiqued — hand it straight back, no job needed. Critique has
    # always been idempotent; that is preserved on both paths.
    if generated.critique:
        payload = CritiqueResponse.from_orm_model(generated.critique).model_dump(mode="json")
        if wait:
            response.status_code = status.HTTP_201_CREATED
            return payload
        response.status_code = status.HTTP_200_OK
        return {
            "job_id": None,
            "kind": "critique",
            "session_id": session_id,
            "status": DONE,
            "stage": "Complete",
            "elapsed_seconds": 0,
            "result": payload,
            "error": None,
        }

    existing = job_registry.find_active("critique", session_id)
    if existing is not None:
        if wait:
            critique_payload = _await_job(existing.id)
            response.status_code = status.HTTP_201_CREATED
            return critique_payload
        return existing.to_dict()

    artwork_meta = _get_artwork_meta(sess, db)
    primary_meta = artwork_meta[0] if artwork_meta else {}
    additional_meta = artwork_meta[1:]
    generated_id = generated.id
    generated_url = generated.image_url
    generated_prompt = generated.prompt_synthesized

    def work(progress) -> dict:
        # Look at the generated image before critiquing it. Without this the
        # critic only ever sees the prompt, so it describes what was *asked for*
        # rather than what the model actually produced.
        progress("Looking at your artwork")
        generated_visual = vision_service.describe_for_critique(generated_url)
        if not generated_visual:
            logger.info(
                f"[critique] session={session_id} no vision reading available; "
                f"critiquing from the prompt alone"
            )

        progress("Writing the critique")
        user_msg = build_critique_user_message(
            reference_artwork=primary_meta,
            generated_artwork_prompt=generated_prompt,
            generated_artwork_url=generated_url,
            generated_visual_reading=generated_visual,
            additional_references=additional_meta,
        )
        raw_output = llm_service.generate_critique(user_msg, primary_meta)

        progress("Saving the critique")
        worker_db = SessionLocal()
        try:
            critique = Critique(
                generated_artwork_id=generated_id,
                reference_critique=raw_output.get("reference_critique", {}),
                generated_critique=raw_output.get("generated_critique", {}),
                comparison=raw_output.get("comparison", ""),
            )
            worker_db.add(critique)
            worker_db.commit()
            worker_db.refresh(critique)
            return CritiqueResponse.from_orm_model(critique).model_dump(mode="json")
        finally:
            worker_db.close()

    job = job_registry.submit(
        kind="critique",
        session_id=session_id,
        user_id=current_user.id,
        work=work,
        initial_stage="Looking at your artwork",
    )

    if wait:
        critique_payload = _await_job(job.id)
        response.status_code = status.HTTP_201_CREATED
        return critique_payload

    response.status_code = status.HTTP_202_ACCEPTED
    return job.to_dict()


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

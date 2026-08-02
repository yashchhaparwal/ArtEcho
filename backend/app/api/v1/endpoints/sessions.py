import json
import os
import time
from pathlib import Path
from typing import Any, List
from datetime import datetime, timezone
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.api.deps import get_db, get_current_user
from app.db.session import SessionLocal
from app.models.user import User
from app.models.artwork import ReferenceArtwork
from app.models.session import ChatSession, SessionReference, SessionStatus
from app.models.message import Message, MessageSender
from app.models.generation import GeneratedArtwork
from app.schemas.session import SessionCreate, SessionResponse, SessionListResponse
from app.schemas.message import MessageCreate, MessageResponse
from app.services.llm_provider import llm_service
from app.services.artwork_analysis import (
    analyze_artwork_by_id,
    analyze_artworks_by_ids,
    build_artwork_meta,
)
from app.core.profiling import profile_request, pop_llm_metrics, StageTimer
import logging

logger = logging.getLogger(__name__)

router = APIRouter()

BASE_DIR = Path(__file__).parent.parent.parent.parent.parent
GENERATED_DIR = BASE_DIR / "generated"

# After this many user turns the generate button unlocks regardless of what the
# model reports. The client's brief leaves conversation length to the user, so
# this is a floor on when generating becomes POSSIBLE — never a ceiling on how
# long the conversation may run.
MIN_TURNS_TO_UNLOCK = 4


@router.post("", response_model=SessionResponse, status_code=status.HTTP_201_CREATED)
def create_session(
    *,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    session_in: SessionCreate,
) -> Any:
    """
    Create a new ChatSession linked to reference artwork(s).
    Triggers initial LLM greeting and opening question.
    """
    if not session_in.reference_artwork_ids:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="At least one reference_artwork_id must be provided",
        )

    # 1. Fetch reference artworks
    artworks = (
        db.query(ReferenceArtwork)
        .filter(ReferenceArtwork.id.in_(session_in.reference_artwork_ids))
        .all()
    )
    if not artworks:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="None of the specified reference artworks were found",
        )

    # Set title based on primary artwork
    primary_title = artworks[0].title
    session_title = f"Conversation on '{primary_title}'" if len(artworks) == 1 else f"Conversation on {len(artworks)} Artworks"

    # 2. Create ChatSession
    chat_session = ChatSession(
        user_id=current_user.id,
        title=session_title,
        status=SessionStatus.ACTIVE,
        context_summary={
            "artistic_preferences": "",
            "personal_context": "",
            "desired_mood": "",
            "color_palette_notes": "",
            "composition_notes": "",
            "inspiration_level": "balanced",
        },
        is_ready_to_generate=False,
        is_saved=False,
    )
    db.add(chat_session)
    db.flush()

    # 3. Create SessionReference rows
    #
    # A user upload with no cached analysis is analysed inline: it has no title,
    # artist or movement to fall back on, so without a visual reading the
    # opening question would be generic — exactly what the brief rules out.
    # Library artworks carry full metadata, so a missing analysis is queued in
    # the background instead of making the user wait for CPU inference.
    artwork_meta_list = []
    pending_analysis: list[str] = []
    for art in artworks:
        session_ref = SessionReference(
            session_id=chat_session.id,
            reference_artwork_id=art.id,
            custom_image_url=art.image_url if art.is_custom_upload else None,
            is_custom_upload=art.is_custom_upload,
        )
        db.add(session_ref)
        if not art.visual_analysis:
            if art.is_custom_upload:
                analysis = analyze_artwork_by_id(art.id)
                if analysis:
                    art.visual_analysis = analysis
            else:
                pending_analysis.append(art.id)
        artwork_meta_list.append(build_artwork_meta(art))

    if pending_analysis:
        background_tasks.add_task(analyze_artworks_by_ids, pending_analysis)

    # 4. Generate initial LLM opening greeting
    llm_output = llm_service.generate_opening_message(artwork_meta_list)

    assistant_msg = Message(
        session_id=chat_session.id,
        sender=MessageSender.ASSISTANT,
        content=llm_output["message"],
    )
    db.add(assistant_msg)

    if "extracted_context" in llm_output:
        chat_session.context_summary = llm_output["extracted_context"]

    db.commit()
    db.refresh(chat_session)
    return chat_session


@router.post("/{session_id}/messages", response_model=MessageResponse)
def create_message(
    *,
    session_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    message_in: MessageCreate,
) -> Any:
    """
    Send a user message in a chat session.
    Invokes LLM turn, updates context_summary, assesses readiness, and returns assistant message.
    """
    with profile_request(f"POST /sessions/{session_id}/messages") as prof:
        # Auth + session lookup. (JWT decode itself happens in the
        # get_current_user dependency, before this body runs.)
        with prof.stage("Session lookup"):
            chat_session = (
                db.query(ChatSession)
                .filter(ChatSession.id == session_id, ChatSession.user_id == current_user.id)
                .first()
            )
        if not chat_session:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Chat session not found",
            )

        # 1. Save user message
        with prof.stage("Save user msg"):
            user_msg = Message(
                session_id=chat_session.id,
                sender=MessageSender.USER,
                content=message_in.content,
            )
            db.add(user_msg)
            db.flush()

        # 2. Build history & turn count
        with prof.stage("History query"):
            all_messages = (
                db.query(Message)
                .filter(Message.session_id == chat_session.id)
                .order_by(Message.created_at.asc())
                .all()
            )

            history = [
                {"sender": "user" if m.sender == MessageSender.USER else "assistant", "content": m.content}
                for m in all_messages[:-1]  # Exclude current user message
            ]

            user_turns_count = sum(1 for m in all_messages if m.sender == MessageSender.USER)

        # 3. Fetch artwork metadata
        with prof.stage("Artwork query"):
            refs = (
                db.query(SessionReference)
                .filter(SessionReference.session_id == chat_session.id)
                .all()
            )
            artwork_meta_list = [
                build_artwork_meta(r.reference_artwork) for r in refs if r.reference_artwork
            ]

        # 4. Invoke LLM turn
        with prof.stage("LLM total"):
            llm_output = llm_service.process_turn(
                history=history,
                current_user_message=message_in.content,
                artwork_metadata_list=artwork_meta_list,
                turn_count=user_turns_count,
                previous_context_summary=chat_session.context_summary,
            )

        # Fold in the provider-side breakdown (Ollama's own timings).
        metrics = pop_llm_metrics()
        if metrics:
            prof.record("  |- prompt eval", metrics.get("prompt_eval_secs", 0.0))
            prof.record("  |- generation", metrics.get("generation_secs", 0.0))
            prof.record("  |- model load", metrics.get("load_secs", 0.0))
            prof.record("  |- json parse", metrics.get("parse_secs", 0.0))
            for key in (
                "prompt_tokens", "generation_tokens", "prompt_chars", "message_count",
                "history_turns", "prompt_tok_per_s", "gen_tok_per_s", "done_reason",
            ):
                prof.note(key, metrics.get(key))
        else:
            prof.note("llm", "heuristic fallback (no Ollama call)")

        # 5. Update ChatSession state
        if "extracted_context" in llm_output:
            chat_session.context_summary = llm_output["extracted_context"]

        # Readiness UNLOCKS the generate button; it never ends the conversation.
        # Derived from the captured context as well as the model's own flag,
        # because a small local model frequently omits the flag entirely. The
        # turn-count clause is the final safety net.
        if (
            llm_output.get("ready_to_generate")
            or llm_service.has_enough_context(chat_session.context_summary)
            or user_turns_count >= MIN_TURNS_TO_UNLOCK
        ):
            chat_session.is_ready_to_generate = True

        # 6. Save assistant message
        with prof.stage("Save assistant msg"):
            assistant_msg = Message(
                session_id=chat_session.id,
                sender=MessageSender.ASSISTANT,
                content=llm_output["message"],
            )
            db.add(assistant_msg)
            db.commit()
            db.refresh(assistant_msg)
        return assistant_msg


@router.post("/{session_id}/messages/stream")
def create_message_stream(
    *,
    session_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    message_in: MessageCreate,
) -> Any:
    """
    Streaming variant of create_message (Server-Sent Events).

    Same end state as the blocking endpoint — user message saved, assistant
    message saved, context_summary merged, readiness assessed — but the prose
    reply is streamed as it is generated instead of after. On this host that
    moves time-to-first-text from ~180s to roughly the prompt-eval time.

    Event types: `token` (text fragment), `done` (final metadata), `error`.
    """
    chat_session = (
        db.query(ChatSession)
        .filter(ChatSession.id == session_id, ChatSession.user_id == current_user.id)
        .first()
    )
    if not chat_session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Chat session not found",
        )

    user_msg = Message(
        session_id=chat_session.id,
        sender=MessageSender.USER,
        content=message_in.content,
    )
    db.add(user_msg)
    db.flush()

    all_messages = (
        db.query(Message)
        .filter(Message.session_id == chat_session.id)
        .order_by(Message.created_at.asc())
        .all()
    )
    history = [
        {"sender": "user" if m.sender == MessageSender.USER else "assistant", "content": m.content}
        for m in all_messages[:-1]
    ]
    user_turns_count = sum(1 for m in all_messages if m.sender == MessageSender.USER)

    refs = (
        db.query(SessionReference)
        .filter(SessionReference.session_id == chat_session.id)
        .all()
    )
    artwork_meta_list = [
        build_artwork_meta(r.reference_artwork) for r in refs if r.reference_artwork
    ]
    previous_context = dict(chat_session.context_summary or {})
    db.commit()

    def event_stream():
        prof = StageTimer(f"POST /sessions/{session_id}/messages/stream")
        collected: List[str] = []
        try:
            # --- Call 1: stream the prose reply -----------------------------
            t0 = time.perf_counter()
            for fragment in llm_service.stream_prose_turn(
                history=history,
                current_user_message=message_in.content,
                artwork_metadata_list=artwork_meta_list,
                previous_context_summary=previous_context,
            ):
                collected.append(fragment)
                yield f"data: {json.dumps({'type': 'token', 'text': fragment})}\n\n"
            prof.record("Call 1 prose (streamed)", time.perf_counter() - t0)
            prose_metrics = pop_llm_metrics() or {}
            for key, value in prose_metrics.items():
                prof.note(f"prose.{key}", value)

            reply_text = "".join(collected).strip()
            if not reply_text:
                raise RuntimeError("empty completion from model")

            # --- Call 2: extract the context delta --------------------------
            t1 = time.perf_counter()
            try:
                delta = llm_service.extract_context(
                    current_user_message=message_in.content,
                    assistant_reply=reply_text,
                    previous_context_summary=previous_context,
                )
            except Exception as exc:
                logger.warning(f"Context extraction failed, keeping previous summary: {exc}")
                delta = {}
            prof.record("Call 2 context", time.perf_counter() - t1)
            ctx_metrics = pop_llm_metrics() or {}
            for key, value in ctx_metrics.items():
                prof.note(f"context.{key}", value)

            merged_context = llm_service._merge_context(previous_context, delta)
            ready = (
                bool(delta.get("ready_to_generate"))
                or llm_service.has_enough_context(merged_context)
                or user_turns_count >= MIN_TURNS_TO_UNLOCK
            )

            # --- Persist ----------------------------------------------------
            t2 = time.perf_counter()
            with SessionLocal() as write_db:
                session_row = (
                    write_db.query(ChatSession)
                    .filter(ChatSession.id == session_id)
                    .first()
                )
                assistant_msg = Message(
                    session_id=session_id,
                    sender=MessageSender.ASSISTANT,
                    content=reply_text,
                )
                write_db.add(assistant_msg)
                if session_row is not None:
                    session_row.context_summary = merged_context
                    if ready:
                        session_row.is_ready_to_generate = True
                write_db.commit()
                write_db.refresh(assistant_msg)
                message_id = assistant_msg.id
                created_at = assistant_msg.created_at.isoformat()
            prof.record("DB write", time.perf_counter() - t2)

            yield "data: " + json.dumps({
                "type": "done",
                "id": message_id,
                "session_id": session_id,
                "sender": "assistant",
                "content": reply_text,
                "created_at": created_at,
                "ready_to_generate": ready,
            }) + "\n\n"
        except Exception as exc:
            logger.exception("Streaming turn failed")
            yield f"data: {json.dumps({'type': 'error', 'detail': str(exc)})}\n\n"
        finally:
            prof.emit()

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/{session_id}/save", response_model=SessionResponse)
def save_session(
    session_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Any:
    """
    Mark a session as saved in the user's gallery.
    """
    chat_session = (
        db.query(ChatSession)
        .filter(ChatSession.id == session_id, ChatSession.user_id == current_user.id)
        .first()
    )
    if not chat_session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Chat session not found",
        )

    chat_session.is_saved = True
    chat_session.saved_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(chat_session)
    return chat_session


@router.delete("/{session_id}")
def delete_session(
    session_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Any:
    """
    Delete a chat session and cascade delete all messages, generated artworks, critiques,
    and associated generated files from local disk.
    """
    chat_session = (
        db.query(ChatSession)
        .filter(ChatSession.id == session_id, ChatSession.user_id == current_user.id)
        .first()
    )
    if not chat_session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Chat session not found",
        )

    # 1. Cleanup generated image files from disk
    generated_artworks = (
        db.query(GeneratedArtwork)
        .filter(GeneratedArtwork.session_id == session_id)
        .all()
    )
    for g in generated_artworks:
        if g.image_url and g.image_url.startswith("/generated/"):
            filename = os.path.basename(g.image_url)
            file_path = GENERATED_DIR / filename
            if file_path.exists():
                try:
                    file_path.unlink()
                except Exception as e:
                    print(f"Warning: Failed to delete generated file {file_path}: {e}")

    # 2. Delete session from DB (cascades)
    db.delete(chat_session)
    db.commit()
    return {"message": "Session deleted successfully"}


@router.get("/{session_id}", response_model=SessionResponse)
def get_session(
    session_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Any:
    """
    Get full session detail with message history and reference artworks.
    """
    chat_session = (
        db.query(ChatSession)
        .filter(ChatSession.id == session_id, ChatSession.user_id == current_user.id)
        .first()
    )
    if not chat_session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Chat session not found",
        )
    return chat_session


@router.get("", response_model=SessionListResponse)
def list_user_sessions(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Any:
    """
    List user's past chat sessions.
    """
    sessions = (
        db.query(ChatSession)
        .filter(ChatSession.user_id == current_user.id)
        .order_by(ChatSession.updated_at.desc())
        .all()
    )
    return SessionListResponse(
        sessions=sessions,
        total=len(sessions),
    )

import json
import os
import threading
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

# One lock per session guarding opening-message generation, so a double-click or
# a re-mounted effect can't write two opening questions into one thread.
_opening_locks: dict[str, threading.Lock] = {}
_opening_locks_guard = threading.Lock()


def _opening_lock_for(session_id: str) -> threading.Lock:
    with _opening_locks_guard:
        return _opening_locks.setdefault(session_id, threading.Lock())


# Context extraction is a second LLM call costing roughly as much as the reply.
# Running it on every other turn halves that load; see the call site for why the
# batched call is nearly as cheap as a single-turn one.
CONTEXT_EXTRACTION_EVERY_N_TURNS = 2


def _should_extract_context(user_turns_count: int) -> bool:
    """True on the turns where the batched extraction is due."""
    return user_turns_count % CONTEXT_EXTRACTION_EVERY_N_TURNS == 0


def _unextracted_turn_count(user_turns_count: int) -> int:
    """
    How many trailing user turns have not been folded into the summary yet.

    Non-zero when a conversation ends on an odd turn, which is exactly when
    /generate has to catch up before synthesising the prompt.
    """
    return user_turns_count % CONTEXT_EXTRACTION_EVERY_N_TURNS


def _recent_exchanges(
    history: List[dict], current_user_message: str, current_reply: str
) -> List[tuple[str, str]]:
    """
    The exchanges covered by this extraction: the turns skipped since the last
    run, plus the one that just completed.

    `history` is every message before the current user turn, oldest first.
    """
    exchanges: List[tuple[str, str]] = []
    pending_user: str | None = None
    # Walk only far enough back to cover the turns we deferred.
    for item in history[-(2 * CONTEXT_EXTRACTION_EVERY_N_TURNS):]:
        if item.get("sender") == "user":
            pending_user = item.get("content", "")
        elif pending_user is not None:
            exchanges.append((pending_user, item.get("content", "")))
            pending_user = None
    # Keep only the deferred ones, then append the exchange just finished.
    exchanges = exchanges[-(CONTEXT_EXTRACTION_EVERY_N_TURNS - 1):] if CONTEXT_EXTRACTION_EVERY_N_TURNS > 1 else []
    exchanges.append((current_user_message, current_reply))
    return exchanges


def _build_opening_prompt(artwork_metadata_list: List[dict]) -> str:
    """
    The instruction that produces the assistant's first question.

    Mirrors `llm_service.generate_opening_message`, but as a bare prompt so it
    can be fed through the streaming path — that method calls the blocking
    JSON-returning endpoint, which cannot emit tokens as they arrive.
    """
    artworks = artwork_metadata_list or []
    titles = ", ".join(
        f"'{a.get('title') or 'their uploaded image'}'"
        + (f" by {a['artist']}" if a.get("artist") and not a.get("is_user_upload") else "")
        for a in artworks
    )
    multi_note = (
        "\nThey chose several references together, so acknowledge what the pieces share "
        "or how they contrast, and ask which quality they want carried into the new work."
        if len(artworks) > 1
        else ""
    )
    return (
        f"The user has just selected the following reference artwork(s): {titles}.{multi_note}\n"
        f"Write a welcoming opening message that names one CONCRETE visual detail you can see in the work "
        f"(use the VISUAL READING above — a colour, a shape, a gesture, a contrast), then ask your first "
        f"question about what specifically draws them to it. Be pointed, not generic."
    )


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
    # A missing visual analysis on a *library* artwork is queued in the
    # background — the metadata carries the conversation until it lands. A user
    # upload has no title, artist or movement to fall back on, so its analysis
    # has to happen before the opening question or that question would be
    # generic; that now runs at the head of the opening stream rather than here,
    # so it no longer delays the response.
    pending_analysis: list[str] = []
    for art in artworks:
        session_ref = SessionReference(
            session_id=chat_session.id,
            reference_artwork_id=art.id,
            custom_image_url=art.image_url if art.is_custom_upload else None,
            is_custom_upload=art.is_custom_upload,
        )
        db.add(session_ref)
        if not art.visual_analysis and not art.is_custom_upload:
            pending_analysis.append(art.id)

    if pending_analysis:
        background_tasks.add_task(analyze_artworks_by_ids, pending_analysis)

    # The opening message is NOT generated here. Writing it takes a full LLM
    # turn — measured at 13-39s on this host — and doing that inline meant the
    # user stared at the library for that long after clicking "Start a
    # Conversation", with a pooled database connection pinned the whole time.
    # The session comes back immediately and the client streams the opening
    # question into the empty thread via /messages/opening/stream.
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


@router.post("/{session_id}/messages/opening/stream")
def create_opening_message_stream(
    *,
    session_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Any:
    """
    Write the assistant's opening question, streamed as Server-Sent Events.

    Session creation used to do this inline and blocked for 13-39s on this host.
    Splitting it out means the chat page opens instantly and the first question
    types itself in, the same way every later reply already does.

    Event types: `status` (slow prerequisite, e.g. vision), `token`, `done`,
    `error`.
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

    refs = (
        db.query(SessionReference)
        .filter(SessionReference.session_id == session_id)
        .all()
    )
    artworks = [r.reference_artwork for r in refs if r.reference_artwork]
    # A user upload with no cached reading has nothing but pixels to go on.
    needs_vision = [a.id for a in artworks if a.is_custom_upload and not a.visual_analysis]
    artwork_ids = [a.id for a in artworks]

    def event_stream():
        prof = StageTimer(f"POST /sessions/{session_id}/messages/opening/stream")
        collected: List[str] = []
        try:
            # Serialise per session: React strict-mode double-effects and
            # double-clicks would otherwise write two opening messages.
            with _opening_lock_for(session_id):
                with SessionLocal() as guard_db:
                    existing = (
                        guard_db.query(Message)
                        .filter(Message.session_id == session_id)
                        .order_by(Message.created_at.asc())
                        .first()
                    )
                    if existing is not None:
                        # Already written — replay it rather than generating a second.
                        yield "data: " + json.dumps({
                            "type": "done",
                            "id": existing.id,
                            "session_id": session_id,
                            "sender": "assistant",
                            "content": existing.content,
                            "created_at": existing.created_at.isoformat(),
                            "ready_to_generate": bool(chat_session.is_ready_to_generate),
                        }) + "\n\n"
                        return

                if needs_vision:
                    yield f"data: {json.dumps({'type': 'status', 'detail': 'Looking at your artwork'})}\n\n"
                    t_vision = time.perf_counter()
                    for artwork_id in needs_vision:
                        try:
                            analyze_artwork_by_id(artwork_id)
                        except Exception as exc:
                            logger.warning(f"Upload vision analysis failed for {artwork_id}: {exc}")
                    prof.record("Vision (uploads)", time.perf_counter() - t_vision)

                # Re-read metadata so any analysis just computed is included.
                with SessionLocal() as meta_db:
                    fresh = (
                        meta_db.query(ReferenceArtwork)
                        .filter(ReferenceArtwork.id.in_(artwork_ids))
                        .all()
                    )
                    artwork_meta_list = [build_artwork_meta(a) for a in fresh]

                opening_prompt = _build_opening_prompt(artwork_meta_list)

                t0 = time.perf_counter()
                for fragment in llm_service.stream_prose_turn(
                    history=[],
                    current_user_message=opening_prompt,
                    artwork_metadata_list=artwork_meta_list,
                    previous_context_summary=dict(chat_session.context_summary or {}),
                    # Prompt eval dominates time-to-first-word on CPU; the
                    # opening question is built from the visual reading, not the
                    # catalogue blurb.
                    include_artwork_description=False,
                ):
                    collected.append(fragment)
                    yield f"data: {json.dumps({'type': 'token', 'text': fragment})}\n\n"
                prof.record("Opening prose (streamed)", time.perf_counter() - t0)
                for key, value in (pop_llm_metrics() or {}).items():
                    prof.note(f"opening.{key}", value)

                reply_text = "".join(collected).strip()
                if not reply_text:
                    # Fall back to the blocking path rather than leaving the
                    # thread empty — a session with no opening question is
                    # unusable.
                    reply_text = llm_service.generate_opening_message(artwork_meta_list)["message"]

                with SessionLocal() as write_db:
                    assistant_msg = Message(
                        session_id=session_id,
                        sender=MessageSender.ASSISTANT,
                        content=reply_text,
                    )
                    write_db.add(assistant_msg)
                    write_db.commit()
                    write_db.refresh(assistant_msg)
                    message_id = assistant_msg.id
                    created_at = assistant_msg.created_at.isoformat()

            yield "data: " + json.dumps({
                "type": "done",
                "id": message_id,
                "session_id": session_id,
                "sender": "assistant",
                "content": reply_text,
                "created_at": created_at,
                "ready_to_generate": False,
            }) + "\n\n"
        except Exception as exc:
            logger.exception("Opening stream failed")
            yield f"data: {json.dumps({'type': 'error', 'detail': str(exc)})}\n\n"
        finally:
            prof.emit()

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


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

            # --- Persist the reply and release the user ---------------------
            #
            # Context extraction is a whole second LLM call, measured at ~19s of
            # the ~49s turn on this host. It used to run BEFORE `done`, so the
            # composer stayed disabled long after the reply had finished
            # printing and the user sat looking at a complete answer they
            # couldn't respond to. Nothing the user does next depends on it, so
            # the reply is saved and announced first and the extraction runs
            # afterwards, reporting back over the same stream.
            t2 = time.perf_counter()
            provisional_ready = (
                llm_service.has_enough_context(previous_context)
                or user_turns_count >= MIN_TURNS_TO_UNLOCK
            )
            with SessionLocal() as write_db:
                assistant_msg = Message(
                    session_id=session_id,
                    sender=MessageSender.ASSISTANT,
                    content=reply_text,
                )
                write_db.add(assistant_msg)
                if provisional_ready:
                    session_row = (
                        write_db.query(ChatSession)
                        .filter(ChatSession.id == session_id)
                        .first()
                    )
                    if session_row is not None:
                        session_row.is_ready_to_generate = True
                write_db.commit()
                write_db.refresh(assistant_msg)
                message_id = assistant_msg.id
                created_at = assistant_msg.created_at.isoformat()
            prof.record("DB write (reply)", time.perf_counter() - t2)

            yield "data: " + json.dumps({
                "type": "done",
                "id": message_id,
                "session_id": session_id,
                "sender": "assistant",
                "content": reply_text,
                "created_at": created_at,
                "ready_to_generate": provisional_ready,
            }) + "\n\n"

            # --- Call 2: extract the context delta (user is already free) ----
            #
            # Run on every second user turn, covering both exchanges since the
            # last run. The call costs about as much as the reply itself and is
            # nearly all fixed overhead, so two turns in one call is close to
            # the price of one — and it halves how often the model swaps between
            # this prompt and the conversation prompt, which was thrashing the
            # prefix cache and slowing the *replies* down. Nothing is dropped:
            # the skipped turn is folded into the next run, and /generate does a
            # catch-up first if a conversation ends on an unextracted turn.
            if not _should_extract_context(user_turns_count):
                logger.info(
                    f"[stream] session={session_id} turn {user_turns_count}: "
                    f"context extraction deferred to the next turn"
                )
                prof.note("context.deferred", True)
                return

            exchanges = _recent_exchanges(history, message_in.content, reply_text)
            t1 = time.perf_counter()
            try:
                delta = llm_service.extract_context_from_exchanges(
                    exchanges=exchanges,
                    previous_context_summary=previous_context,
                )
            except Exception as exc:
                logger.warning(f"Context extraction failed, keeping previous summary: {exc}")
                delta = {}
            prof.record(
                f"Call 2 context ({len(exchanges)} exchange(s), after reply)",
                time.perf_counter() - t1,
            )
            ctx_metrics = pop_llm_metrics() or {}
            for key, value in ctx_metrics.items():
                prof.note(f"context.{key}", value)

            merged_context = llm_service._merge_context(previous_context, delta)
            ready = (
                provisional_ready
                or bool(delta.get("ready_to_generate"))
                or llm_service.has_enough_context(merged_context)
            )

            with SessionLocal() as write_db:
                session_row = (
                    write_db.query(ChatSession)
                    .filter(ChatSession.id == session_id)
                    .first()
                )
                if session_row is not None:
                    session_row.context_summary = merged_context
                    if ready:
                        session_row.is_ready_to_generate = True
                    write_db.commit()

            yield "data: " + json.dumps({
                "type": "context",
                "session_id": session_id,
                "context_summary": merged_context,
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

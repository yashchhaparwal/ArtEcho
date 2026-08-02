import os
import uuid
from pathlib import Path
from typing import List, Optional, Any
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, UploadFile, File, status
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from sqlalchemy import or_, func

from app.api.deps import get_db, get_current_user
from app.models.artwork import ReferenceArtwork
from app.models.user import User
from app.schemas.artwork import ReferenceArtworkResponse, ArtworkListResponse
from app.services.artwork_analysis import analyze_artwork_by_id, analyze_artworks_by_ids

router = APIRouter()

# backend/uploads — must match the StaticFiles mount in app/main.py
UPLOAD_DIR = str(Path(__file__).resolve().parents[4] / "uploads")
ALLOWED_CONTENT_TYPES = {"image/jpeg", "image/png", "image/webp"}
ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
MAX_FILE_SIZE_BYTES = 10 * 1024 * 1024  # 10 MB

# A declared content-type and extension are both trivially spoofable, so the
# bytes themselves decide whether we store the file.
IMAGE_MAGIC_BYTES = (
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"\x89PNG\r\n\x1a\n", "image/png"),
)


def ensure_upload_dir():
    os.makedirs(UPLOAD_DIR, exist_ok=True)


def sniff_image_type(content: bytes) -> Optional[str]:
    """Return the real image type from magic bytes, or None if it isn't one."""
    for signature, mime in IMAGE_MAGIC_BYTES:
        if content.startswith(signature):
            return mime
    # WebP: "RIFF" .... "WEBP"
    if content[:4] == b"RIFF" and content[8:12] == b"WEBP":
        return "image/webp"
    return None


@router.get("", response_model=ArtworkListResponse)
def list_artworks(
    db: Session = Depends(get_db),
    search: Optional[str] = Query(None, description="Search by title, artist, or description"),
    artist: Optional[str] = Query(None, description="Filter by artist name"),
    movement: Optional[str] = Query(None, description="Filter by movement/style"),
    include_uploads: bool = Query(True, description="Include user-uploaded artworks"),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(20, ge=1, le=100, description="Results per page"),
) -> Any:
    """
    List reference artworks from the public library.
    Supports full-text search and filtering by artist/movement.
    """
    query = db.query(ReferenceArtwork)

    if not include_uploads:
        query = query.filter(ReferenceArtwork.is_custom_upload == False)

    if search:
        search_term = f"%{search.lower()}%"
        query = query.filter(
            or_(
                func.lower(ReferenceArtwork.title).like(search_term),
                func.lower(ReferenceArtwork.artist).like(search_term),
                func.lower(ReferenceArtwork.description).like(search_term),
            )
        )

    if artist:
        query = query.filter(
            func.lower(ReferenceArtwork.artist).like(f"%{artist.lower()}%")
        )

    if movement:
        query = query.filter(
            func.lower(ReferenceArtwork.movement_style).like(f"%{movement.lower()}%")
        )

    total = query.count()
    artworks = (
        query
        .order_by(ReferenceArtwork.created_at.asc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    return ArtworkListResponse(
        artworks=artworks,
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/{artwork_id}", response_model=ReferenceArtworkResponse)
def get_artwork(
    artwork_id: str,
    db: Session = Depends(get_db),
) -> Any:
    """
    Get a single reference artwork by ID.
    """
    artwork = db.query(ReferenceArtwork).filter(ReferenceArtwork.id == artwork_id).first()
    if not artwork:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Artwork with id '{artwork_id}' not found",
        )
    return artwork


@router.post("/upload", response_model=List[ReferenceArtworkResponse], status_code=status.HTTP_201_CREATED)
async def upload_artworks(
    background_tasks: BackgroundTasks,
    files: List[UploadFile] = File(..., description="One or more image files (JPEG, PNG, WebP, max 10MB each)"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Any:
    """
    Upload one or more reference images.
    Validates file type (JPEG/PNG/WebP) and size (max 10MB).
    Stores files to local /uploads directory, creates a ReferenceArtwork record per file.
    Requires authentication.

    Each upload is queued for local vision analysis so the assistant can ask
    questions about what is actually in the picture, not just its filename.
    """
    ensure_upload_dir()

    if not files:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No files provided",
        )

    created_artworks = []

    for file in files:
        # --- Validate content type ---
        content_type = file.content_type or ""
        ext = os.path.splitext(file.filename or "")[1].lower()

        if content_type not in ALLOWED_CONTENT_TYPES or ext not in ALLOWED_EXTENSIONS:
            raise HTTPException(
                status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                detail=(
                    f"File '{file.filename}' has unsupported type '{content_type}'. "
                    f"Only JPEG, PNG, and WebP images are accepted."
                ),
            )

        # --- Read and validate file size ---
        contents = await file.read()
        if len(contents) > MAX_FILE_SIZE_BYTES:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=(
                    f"File '{file.filename}' exceeds the 10 MB size limit "
                    f"({len(contents) / (1024*1024):.1f} MB uploaded)."
                ),
            )

        # --- Verify the bytes really are an image, whatever the client claimed ---
        if sniff_image_type(contents) is None:
            raise HTTPException(
                status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                detail=(
                    f"File '{file.filename}' is not a valid JPEG, PNG, or WebP image. "
                    f"Please upload a real image file."
                ),
            )

        # --- Save to disk ---
        unique_filename = f"{uuid.uuid4()}{ext}"
        save_path = os.path.join(UPLOAD_DIR, unique_filename)
        with open(save_path, "wb") as f:
            f.write(contents)

        # Relative URL served via /uploads static mount
        image_url = f"/uploads/{unique_filename}"

        # --- Create DB record ---
        original_name = os.path.splitext(file.filename or "Untitled")[0]
        artwork = ReferenceArtwork(
            title=original_name,
            artist=current_user.name or current_user.email,
            image_url=image_url,
            is_public_domain=False,
            is_custom_upload=True,
            uploaded_by_user_id=current_user.id,
        )
        db.add(artwork)
        db.flush()  # Get the generated ID without committing
        created_artworks.append(artwork)

    db.commit()
    for artwork in created_artworks:
        db.refresh(artwork)

    # Vision analysis runs after the response so the upload stays fast; the
    # conversation degrades to metadata-only if it hasn't finished in time.
    background_tasks.add_task(
        analyze_artworks_by_ids, [artwork.id for artwork in created_artworks]
    )

    return created_artworks


@router.post("/{artwork_id}/analyze", response_model=ReferenceArtworkResponse)
def analyze_artwork(
    artwork_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    force: bool = Query(False, description="Recompute even if an analysis already exists"),
) -> Any:
    """
    Run (or re-run) vision analysis for a single artwork and return the updated
    record. Synchronous — useful for backfilling library items and for testing.
    """
    artwork = db.query(ReferenceArtwork).filter(ReferenceArtwork.id == artwork_id).first()
    if not artwork:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Artwork with id '{artwork_id}' not found",
        )

    analyze_artwork_by_id(artwork_id, force=force)
    db.refresh(artwork)
    return artwork

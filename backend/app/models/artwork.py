import uuid
from datetime import datetime, timezone
from typing import Any, Optional
from sqlalchemy import String, Boolean, Text, DateTime, ForeignKey, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import Base


class ReferenceArtwork(Base):
    __tablename__ = "reference_artworks"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid.uuid4())
    )
    title: Mapped[str] = mapped_column(String, nullable=False, index=True)
    artist: Mapped[str] = mapped_column(String, nullable=False, index=True)
    year: Mapped[str] = mapped_column(String, nullable=True)
    movement_style: Mapped[str] = mapped_column(String, nullable=True, index=True)
    medium: Mapped[str] = mapped_column(String, nullable=True)
    description: Mapped[str] = mapped_column(Text, nullable=True)
    source_attribution: Mapped[str] = mapped_column(String, nullable=True)
    image_url: Mapped[str] = mapped_column(String, nullable=False)
    dominant_color: Mapped[str] = mapped_column(String, nullable=True)
    is_public_domain: Mapped[bool] = mapped_column(Boolean, default=True)
    # Cached output of the local vision model — what the image actually depicts.
    # Populated once per artwork (analysis is expensive on CPU) and reused for
    # every conversation that references it.
    visual_analysis: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)
    # For user uploads
    is_custom_upload: Mapped[bool] = mapped_column(Boolean, default=False)
    uploaded_by_user_id: Mapped[str] = mapped_column(
        String, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    session_references = relationship("SessionReference", back_populates="reference_artwork")
    uploaded_by = relationship("User", foreign_keys=[uploaded_by_user_id])

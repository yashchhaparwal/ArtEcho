import uuid
import enum
from datetime import datetime, timezone
from sqlalchemy import String, Text, JSON, Boolean, Enum as SQLEnum, ForeignKey, DateTime
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import Base


class InspirationLevel(str, enum.Enum):
    LOOSE = "loose"
    BALANCED = "balanced"
    NEAR = "near"


class GeneratedArtwork(Base):
    __tablename__ = "generated_artworks"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid.uuid4())
    )
    session_id: Mapped[str] = mapped_column(
        String, ForeignKey("chat_sessions.id", ondelete="CASCADE"), nullable=False
    )
    image_url: Mapped[str] = mapped_column(String, nullable=False)
    prompt_synthesized: Mapped[str] = mapped_column(Text, nullable=False)
    inspiration_level: Mapped[InspirationLevel] = mapped_column(
        SQLEnum(InspirationLevel), default=InspirationLevel.BALANCED
    )
    resolution: Mapped[str] = mapped_column(String, default="1024x1024")
    model_provider: Mapped[str] = mapped_column(String, default="openai")
    generation_index: Mapped[int] = mapped_column(default=1)  # 1 = first, 2 = regen, etc.
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    session = relationship("ChatSession", back_populates="generated_artworks")
    critique = relationship(
        "Critique", back_populates="generated_artwork", uselist=False, cascade="all, delete-orphan"
    )


class Critique(Base):
    __tablename__ = "critiques"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid.uuid4())
    )
    generated_artwork_id: Mapped[str] = mapped_column(
        String, ForeignKey("generated_artworks.id", ondelete="CASCADE"), unique=True, nullable=False
    )

    # Per-artwork structured critique
    reference_critique: Mapped[dict] = mapped_column(JSON, nullable=True)
    generated_critique: Mapped[dict] = mapped_column(JSON, nullable=True)
    comparison: Mapped[str] = mapped_column(Text, nullable=True)

    # Legacy flat fields (kept for backward compat, nullable)
    summary_content: Mapped[str] = mapped_column(Text, nullable=True)
    composition_analysis: Mapped[str] = mapped_column(Text, nullable=True)
    color_theory_analysis: Mapped[str] = mapped_column(Text, nullable=True)
    symbolism_analysis: Mapped[str] = mapped_column(Text, nullable=True)
    emotional_impact_analysis: Mapped[str] = mapped_column(Text, nullable=True)
    comparison_analysis: Mapped[str] = mapped_column(Text, nullable=True)
    strengths: Mapped[dict] = mapped_column(JSON, default=list)
    weaknesses: Mapped[dict] = mapped_column(JSON, default=list)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    generated_artwork = relationship("GeneratedArtwork", back_populates="critique")

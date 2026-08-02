import uuid
import enum
from datetime import datetime, timezone
from sqlalchemy import String, Boolean, JSON, Enum as SQLEnum, ForeignKey, DateTime
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import Base


class SessionStatus(str, enum.Enum):
    ACTIVE = "active"
    COMPLETED = "completed"
    ARCHIVED = "archived"


class ChatSession(Base):
    __tablename__ = "chat_sessions"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid.uuid4())
    )
    user_id: Mapped[str] = mapped_column(
        String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    title: Mapped[str] = mapped_column(String, default="New Art Conversation")
    status: Mapped[SessionStatus] = mapped_column(
        SQLEnum(SessionStatus), default=SessionStatus.ACTIVE
    )
    context_summary: Mapped[dict] = mapped_column(JSON, default=dict, nullable=True)
    is_ready_to_generate: Mapped[bool] = mapped_column(Boolean, default=False)
    is_saved: Mapped[bool] = mapped_column(Boolean, default=False)
    saved_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    user = relationship("User", back_populates="chat_sessions")
    session_references = relationship(
        "SessionReference", back_populates="session", cascade="all, delete-orphan"
    )
    messages = relationship(
        "Message", back_populates="session", cascade="all, delete-orphan", order_by="Message.created_at.asc()"
    )
    generated_artworks = relationship(
        "GeneratedArtwork", back_populates="session", cascade="all, delete-orphan", order_by="GeneratedArtwork.generation_index.asc()"
    )


class SessionReference(Base):
    __tablename__ = "session_references"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid.uuid4())
    )
    session_id: Mapped[str] = mapped_column(
        String, ForeignKey("chat_sessions.id", ondelete="CASCADE"), nullable=False
    )
    reference_artwork_id: Mapped[str] = mapped_column(
        String, ForeignKey("reference_artworks.id", ondelete="SET NULL"), nullable=True
    )
    custom_image_url: Mapped[str] = mapped_column(String, nullable=True)
    is_custom_upload: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    session = relationship("ChatSession", back_populates="session_references")
    reference_artwork = relationship("ReferenceArtwork", back_populates="session_references")

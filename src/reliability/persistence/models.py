"""SQLAlchemy 2.0 models (SQLite)."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    """Naive UTC timestamp (SQLite does not keep tzinfo)."""
    return datetime.now(UTC).replace(tzinfo=None)


class Base(DeclarativeBase):
    pass


class Analysis(Base):
    __tablename__ = "analysis"

    id: Mapped[int] = mapped_column(primary_key=True)
    input_type: Mapped[str] = mapped_column(String(8))
    original_input: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), default="PENDING", index=True)
    depth: Mapped[str] = mapped_column(String(12), default="rapida")
    pipeline_version: Mapped[str] = mapped_column(String(32), default="")
    prompt_version: Mapped[str] = mapped_column(String(32), default="")
    model_name: Mapped[str] = mapped_column(String(128), default="")
    llm_base_url: Mapped[str] = mapped_column(String(256), default="")
    overall_status: Mapped[str | None] = mapped_column(String(64), nullable=True)
    overall_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    domain: Mapped[str | None] = mapped_column(String(256), nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    media_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    media_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    step_label: Mapped[str] = mapped_column(String(128), default="Na fila")
    warnings: Mapped[list] = mapped_column(JSON, default=list)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0)
    processing_time_ms: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    claims: Mapped[list[Claim]] = relationship(
        back_populates="analysis", cascade="all, delete-orphan", order_by="Claim.id"
    )
    tags: Mapped[list[TagAssignment]] = relationship(
        back_populates="analysis", cascade="all, delete-orphan", order_by="TagAssignment.id"
    )
    events: Mapped[list[ProgressEvent]] = relationship(
        back_populates="analysis", cascade="all, delete-orphan", order_by="ProgressEvent.id"
    )
    feedback: Mapped[list[UserFeedback]] = relationship(
        back_populates="analysis", cascade="all, delete-orphan"
    )
    sources: Mapped[list[Source]] = relationship(
        back_populates="analysis", cascade="all, delete-orphan"
    )


class Claim(Base):
    __tablename__ = "claim"

    id: Mapped[int] = mapped_column(primary_key=True)
    analysis_id: Mapped[int] = mapped_column(ForeignKey("analysis.id"), index=True)
    text: Mapped[str] = mapped_column(Text)
    claim_type: Mapped[str] = mapped_column(String(32))
    importance: Mapped[int] = mapped_column(Integer, default=2)
    time_sensitive: Mapped[bool] = mapped_column(Boolean, default=False)
    requires_external_evidence: Mapped[bool] = mapped_column(Boolean, default=True)
    verification_query: Mapped[str] = mapped_column(Text, default="")
    source_quote: Mapped[str] = mapped_column(Text, default="")
    verification_status: Mapped[str] = mapped_column(String(32), default="inconclusiva")
    rationale: Mapped[str | None] = mapped_column(Text, nullable=True)

    analysis: Mapped[Analysis] = relationship(back_populates="claims")
    evidences: Mapped[list[Evidence]] = relationship(
        back_populates="claim", cascade="all, delete-orphan", order_by="Evidence.id"
    )


class Source(Base):
    __tablename__ = "source"

    id: Mapped[int] = mapped_column(primary_key=True)
    analysis_id: Mapped[int] = mapped_column(ForeignKey("analysis.id"), index=True)
    url: Mapped[str] = mapped_column(Text)
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    publisher: Mapped[str | None] = mapped_column(String(256), nullable=True)
    domain: Mapped[str | None] = mapped_column(String(256), nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    is_paywalled: Mapped[bool] = mapped_column(Boolean, default=False)

    analysis: Mapped[Analysis] = relationship(back_populates="sources")


class Evidence(Base):
    __tablename__ = "evidence"

    id: Mapped[int] = mapped_column(primary_key=True)
    claim_id: Mapped[int] = mapped_column(ForeignKey("claim.id"), index=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("source.id"))
    stance: Mapped[str] = mapped_column(String(24))
    relevance: Mapped[float] = mapped_column(Float, default=0.0)
    exact_quote: Mapped[str] = mapped_column(Text)
    omits_context: Mapped[bool] = mapped_column(Boolean, default=False)

    claim: Mapped[Claim] = relationship(back_populates="evidences")
    source: Mapped[Source] = relationship()


class TagAssignment(Base):
    __tablename__ = "tag_assignment"

    id: Mapped[int] = mapped_column(primary_key=True)
    analysis_id: Mapped[int] = mapped_column(ForeignKey("analysis.id"), index=True)
    claim_id: Mapped[int | None] = mapped_column(ForeignKey("claim.id"), nullable=True)
    tag_code: Mapped[str] = mapped_column(String(48))
    justification: Mapped[str] = mapped_column(Text)

    analysis: Mapped[Analysis] = relationship(back_populates="tags")


class UserFeedback(Base):
    __tablename__ = "user_feedback"

    id: Mapped[int] = mapped_column(primary_key=True)
    analysis_id: Mapped[int] = mapped_column(ForeignKey("analysis.id"), index=True)
    is_accurate: Mapped[bool] = mapped_column(Boolean)
    correction_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    analysis: Mapped[Analysis] = relationship(back_populates="feedback")


class ProgressEvent(Base):
    __tablename__ = "progress_event"

    id: Mapped[int] = mapped_column(primary_key=True)
    analysis_id: Mapped[int] = mapped_column(ForeignKey("analysis.id"), index=True)
    ts: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    step: Mapped[str] = mapped_column(String(24))
    message: Mapped[str] = mapped_column(Text)

    analysis: Mapped[Analysis] = relationship(back_populates="events")

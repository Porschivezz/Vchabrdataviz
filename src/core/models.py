"""SQLAlchemy ORM models."""

from __future__ import annotations

import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Column,
    DateTime,
    Float,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase

from src.core.config import settings


class Base(DeclarativeBase):
    pass


class Article(Base):
    __tablename__ = "articles"
    __table_args__ = (UniqueConstraint("link", name="uq_article_link"),)

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source = Column(String(32), nullable=False, index=True)
    title = Column(Text, nullable=False)
    link = Column(Text, nullable=False, unique=True)
    published_at = Column(DateTime, nullable=True)
    raw_text = Column(Text, nullable=False, default="")
    native_tags = Column(JSONB, nullable=False, default=list)
    estimated_tokens = Column(Integer, nullable=False, default=0)

    status = Column(
        String(32),
        nullable=False,
        default="PENDING",
        index=True,
    )

    summary = Column(Text, nullable=True)
    entities = Column(JSONB, nullable=True)
    sentiment = Column(Float, nullable=True)
    embedding = Column(Vector(settings.embedding_dimensions), nullable=True)

    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(
        DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    def __repr__(self) -> str:
        return f"<Article {self.source}:{self.title[:40]}>"


class IngestionRun(Base):
    """Track each scraping run for archive coverage visualization."""
    __tablename__ = "ingestion_runs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source = Column(String(32), nullable=False, index=True)
    since = Column(DateTime, nullable=False)
    until = Column(DateTime, nullable=False)
    total_fetched = Column(Integer, nullable=False, default=0)
    new_articles = Column(Integer, nullable=False, default=0)
    skipped = Column(Integer, nullable=False, default=0)
    queued = Column(Integer, nullable=False, default=0)
    status = Column(String(32), nullable=False, default="RUNNING")  # RUNNING, SUCCESS, FAILED
    error_message = Column(Text, nullable=True)
    started_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    finished_at = Column(DateTime, nullable=True)


class DailyDigest(Base):
    """Pre-computed daily narrative digest."""
    __tablename__ = "daily_digests"
    __table_args__ = (UniqueConstraint("digest_date", "source", name="uq_digest_date_source"),)

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    digest_date = Column(DateTime, nullable=False, index=True)
    source = Column(String(32), nullable=False, default="all")
    narrative = Column(Text, nullable=False)
    top_entities = Column(JSONB, nullable=True)
    avg_sentiment = Column(Float, nullable=True)
    article_count = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

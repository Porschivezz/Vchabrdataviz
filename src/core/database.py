"""SQLAlchemy engine, session factory, and pgvector initialization."""

from __future__ import annotations

import logging

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, Session

from src.core.config import settings

logger = logging.getLogger(__name__)

engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,
    pool_size=5,
    max_overflow=10,
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_session() -> Session:
    return SessionLocal()


def init_db() -> None:
    """Create pgvector extension and all tables, apply migrations."""
    with engine.begin() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))

    from src.core.models import Base  # noqa: F811
    Base.metadata.create_all(bind=engine)

    dim = settings.embedding_dimensions
    with engine.begin() as conn:
        # Migrate embedding column to configured dimensions
        conn.execute(text(
            f"ALTER TABLE articles "
            f"ALTER COLUMN embedding TYPE vector({dim}) "
            f"USING NULL"
        ))
        # Add new columns if missing
        conn.execute(text(
            "ALTER TABLE articles ADD COLUMN IF NOT EXISTS sentiment FLOAT"
        ))
        conn.execute(text(
            "ALTER TABLE articles ADD COLUMN IF NOT EXISTS hype_score FLOAT"
        ))
        conn.execute(text(
            "ALTER TABLE articles ADD COLUMN IF NOT EXISTS relations JSONB"
        ))
        # Create telegram_channels table if not exists (handled by create_all,
        # but ensure columns exist for upgrades)
        conn.execute(text(
            "CREATE TABLE IF NOT EXISTS telegram_channels ("
            "  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),"
            "  username VARCHAR(128) NOT NULL UNIQUE,"
            "  title TEXT,"
            "  enabled BOOLEAN NOT NULL DEFAULT TRUE,"
            "  last_message_id INTEGER,"
            "  created_at TIMESTAMP NOT NULL DEFAULT NOW(),"
            "  last_fetched_at TIMESTAMP,"
            "  post_count INTEGER NOT NULL DEFAULT 0"
            ")"
        ))
        # Add GIN index for FTS (hybrid search)
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS idx_articles_fts "
            "ON articles USING gin(to_tsvector('russian', coalesce(title,'') || ' ' || coalesce(summary,'')))"
        ))
    logger.info("Database initialized (embedding dim=%d)", dim)

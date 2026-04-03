"""Configuration for RU News Collector."""

from __future__ import annotations

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql+psycopg2://postgres:postgres@localhost:5432/ru_news"
    api_token: str = "change-me"
    poll_interval_minutes: int = 15
    api_host: str = "0.0.0.0"
    api_port: int = 8100

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()

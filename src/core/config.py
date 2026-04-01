"""Application configuration loaded from environment variables."""

from __future__ import annotations

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # --- Database ---
    database_url: str = "postgresql+psycopg2://postgres:postgres@db:5432/monitoring"

    # --- OpenRouter / LiteLLM ---
    openrouter_api_key: str = ""
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    llm_model: str = "openai/gpt-4o-mini"
    embedding_model: str = "openai/text-embedding-3-small"

    # Cost per 1 M tokens (USD)
    llm_input_cost_per_1m: float = 0.15
    llm_output_cost_per_1m: float = 0.60
    embedding_cost_per_1m: float = 0.02

    # --- Auto-trigger ---
    auto_analyze_keywords: str = "python,ml,ai,data science,llm,gpt"

    # --- Admin ---
    admin_password: str = "changeme123"

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"

    @property
    def keywords_list(self) -> list[str]:
        """Return lower-cased keyword list."""
        return [k.strip().lower() for k in self.auto_analyze_keywords.split(",") if k.strip()]


settings = Settings()

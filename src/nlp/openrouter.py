"""OpenRouter LLM provider using litellm."""

from __future__ import annotations

import json
import logging
import os

import litellm

from src.core.config import settings
from src.nlp.base import AnalysisResult, BaseLLMProvider

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
You are an expert analyst. Given an article, produce a JSON object with exactly two keys:
- "summary": a concise summary (3-5 sentences) in the article's language.
- "entities": an object with keys "persons", "organizations", "technologies", "weak_signals", \
each being a list of strings. "weak_signals" are emerging trends or early indicators of change \
that are not yet mainstream.
Return ONLY valid JSON, no markdown fences."""


class OpenRouterProvider(BaseLLMProvider):
    """LLM provider that routes through OpenRouter via litellm."""

    def __init__(self) -> None:
        os.environ["OPENROUTER_API_KEY"] = settings.openrouter_api_key
        os.environ["OPENROUTER_API_BASE"] = settings.openrouter_base_url

    def summarize_and_extract(self, text: str, title: str = "") -> AnalysisResult:
        # Truncate very long texts to ~12k tokens worth of chars
        max_chars = 48_000
        truncated = text[:max_chars]

        user_msg = f"Article title: {title}\n\n{truncated}" if title else truncated

        try:
            response = litellm.completion(
                model=f"openrouter/{settings.llm_model}",
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_msg},
                ],
                temperature=0.2,
                max_tokens=1024,
                api_key=settings.openrouter_api_key,
                api_base=settings.openrouter_base_url,
            )
        except Exception as exc:
            logger.error("LLM completion failed: %s", exc)
            return AnalysisResult(summary="[LLM error]", entities={})

        raw = response.choices[0].message.content.strip()

        # Parse JSON, stripping potential markdown fences
        json_str = raw
        if json_str.startswith("```"):
            lines = json_str.splitlines()
            lines = [l for l in lines if not l.startswith("```")]
            json_str = "\n".join(lines)

        try:
            parsed = json.loads(json_str)
        except json.JSONDecodeError:
            logger.warning("LLM returned non-JSON: %s", raw[:200])
            return AnalysisResult(summary=raw[:500], entities={})

        summary = parsed.get("summary", "")
        entities = parsed.get("entities", {})

        # Now get the embedding
        embedding = self.embed(f"{title}\n{summary}")

        return AnalysisResult(summary=summary, entities=entities, embedding=embedding)

    def embed(self, text: str) -> list[float]:
        # Truncate for embedding model (8k token limit ~ 32k chars)
        truncated = text[:32_000]

        try:
            response = litellm.embedding(
                model=f"openrouter/{settings.embedding_model}",
                input=[truncated],
                api_key=settings.openrouter_api_key,
                api_base=settings.openrouter_base_url,
            )
            return response.data[0]["embedding"]
        except Exception as exc:
            logger.error("Embedding request failed: %s", exc)
            return [0.0] * 4096

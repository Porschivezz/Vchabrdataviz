"""OpenRouter LLM provider using litellm + instructor for structured outputs."""

from __future__ import annotations

import json
import logging
import os

import litellm
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from src.core.config import settings
from src.nlp.base import AnalysisResult, BaseLLMProvider

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
You are an expert analyst. Given an article, produce a JSON object with exactly these keys:
- "summary": a concise summary (3-5 sentences) in the article's language.
- "entities": an object with keys "persons", "organizations", "technologies", "weak_signals", \
each being a list of strings. "weak_signals" are emerging trends or early indicators of change \
that are not yet mainstream — focus on novel ideas, nascent technologies, regulatory shifts.
- "relations": a list of relationship triples. Each triple is an object with keys \
"subject" (str), "predicate" (str — e.g. "инвестирует в", "конкурирует с", "использует", \
"запускает", "судится с", "приобретает", "партнёрство с"), "object" (str). \
Extract 2-5 most important relationships from the article.
- "sentiment": a float from -1.0 (very negative) to 1.0 (very positive), representing \
the overall tone of the article. 0.0 is neutral.
- "hype_score": a float from 0.0 to 1.0 — how much hype/excitement the article generates. \
0.0 is dry factual, 1.0 is maximum hype/controversy.
Return ONLY valid JSON, no markdown fences."""


class OpenRouterProvider(BaseLLMProvider):
    """LLM provider that routes through OpenRouter via litellm."""

    def __init__(self) -> None:
        os.environ["OPENROUTER_API_KEY"] = settings.openrouter_api_key
        os.environ["OPENROUTER_API_BASE"] = settings.openrouter_base_url

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=2, min=2, max=30),
        retry=retry_if_exception_type((litellm.exceptions.APIError, litellm.exceptions.Timeout, ConnectionError)),
        reraise=True,
    )
    def _llm_completion(self, messages: list[dict], **kwargs) -> str:
        """Call LLM with retry logic. Returns raw content string."""
        response = litellm.completion(
            model=f"openrouter/{settings.llm_model}",
            messages=messages,
            api_key=settings.openrouter_api_key,
            api_base=settings.openrouter_base_url,
            **kwargs,
        )
        return response.choices[0].message.content.strip()

    def summarize_and_extract(self, text: str, title: str = "") -> AnalysisResult:
        # Truncate very long texts to ~12k tokens worth of chars
        max_chars = 48_000
        truncated = text[:max_chars]

        user_msg = f"Article title: {title}\n\n{truncated}" if title else truncated

        try:
            raw = self._llm_completion(
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_msg},
                ],
                temperature=0.2,
                max_tokens=1024,
            )
        except Exception as exc:
            logger.error("LLM completion failed after retries: %s", exc)
            return AnalysisResult(summary="[LLM error]", entities={})

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
        relations = parsed.get("relations", [])
        sentiment = parsed.get("sentiment")
        hype_score = parsed.get("hype_score")

        # Clamp sentiment to [-1, 1]
        if sentiment is not None:
            try:
                sentiment = max(-1.0, min(1.0, float(sentiment)))
            except (TypeError, ValueError):
                sentiment = None

        # Clamp hype_score to [0, 1]
        if hype_score is not None:
            try:
                hype_score = max(0.0, min(1.0, float(hype_score)))
            except (TypeError, ValueError):
                hype_score = None

        # Validate relations format
        valid_relations = []
        if isinstance(relations, list):
            for r in relations:
                if isinstance(r, dict) and all(k in r for k in ("subject", "predicate", "object")):
                    valid_relations.append({
                        "subject": str(r["subject"]),
                        "predicate": str(r["predicate"]),
                        "object": str(r["object"]),
                    })

        # Now get the embedding
        embedding = self.embed(f"{title}\n{summary}")

        return AnalysisResult(
            summary=summary,
            entities=entities,
            relations=valid_relations,
            sentiment=sentiment,
            hype_score=hype_score,
            embedding=embedding,
        )

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=2, min=2, max=30),
        retry=retry_if_exception_type((litellm.exceptions.APIError, litellm.exceptions.Timeout, ConnectionError)),
        reraise=True,
    )
    def embed(self, text: str) -> list[float]:
        # Truncate for embedding model (8k token limit ~ 32k chars)
        truncated = text[:32_000]
        dim = settings.embedding_dimensions

        try:
            response = litellm.embedding(
                model=f"openrouter/{settings.embedding_model}",
                input=[truncated],
                api_key=settings.openrouter_api_key,
                api_base=settings.openrouter_base_url,
                dimensions=dim,
            )
            vec = response.data[0]["embedding"]
            # Ensure correct dimensions
            if len(vec) != dim:
                logger.warning("Embedding returned %d dims, expected %d", len(vec), dim)
                return [0.0] * dim
            return vec
        except Exception as exc:
            logger.error("Embedding request failed: %s", exc)
            return [0.0] * dim

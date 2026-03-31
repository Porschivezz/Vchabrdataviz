"""Abstract base class for LLM providers."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class AnalysisResult:
    """Output of the LLM analysis pipeline for a single article."""
    summary: str = ""
    entities: dict = field(default_factory=dict)
    embedding: list[float] = field(default_factory=list)


class BaseLLMProvider(ABC):
    """Interface every LLM provider must implement."""

    @abstractmethod
    def summarize_and_extract(self, text: str, title: str = "") -> AnalysisResult:
        """Summarize text and extract named entities / weak signals."""
        ...

    @abstractmethod
    def embed(self, text: str) -> list[float]:
        """Return a 1536-dim embedding vector for the text."""
        ...

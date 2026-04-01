"""Entity normalization using synonym dictionary + fuzzy matching."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from thefuzz import fuzz

logger = logging.getLogger(__name__)

_SYNONYMS_PATH = Path(__file__).parent / "synonyms.json"
_FUZZY_THRESHOLD = 85  # minimum similarity score for fuzzy match


def _load_synonyms() -> dict[str, dict[str, list[str]]]:
    """Load synonym mapping: {category: {canonical: [aliases]}}."""
    try:
        with open(_SYNONYMS_PATH, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        logger.warning("synonyms.json not found at %s", _SYNONYMS_PATH)
        return {}


# Build reverse lookup on module load: {category: {alias_lower: canonical}}
_synonyms = _load_synonyms()
_reverse: dict[str, dict[str, str]] = {}
for _cat, _mapping in _synonyms.items():
    _reverse[_cat] = {}
    for canonical, aliases in _mapping.items():
        _reverse[_cat][canonical.lower()] = canonical
        for alias in aliases:
            _reverse[_cat][alias.lower()] = canonical


def normalize_entity(name: str, category: str) -> str:
    """Normalize an entity name using exact match then fuzzy match.

    Args:
        name: Raw entity string from LLM output.
        category: One of "persons", "organizations", "technologies".

    Returns:
        Canonical form if matched, otherwise original name stripped.
    """
    stripped = name.strip()
    if not stripped:
        return stripped

    lookup = _reverse.get(category, {})

    # 1. Exact match (case-insensitive)
    key = stripped.lower()
    if key in lookup:
        return lookup[key]

    # 2. Fuzzy match against all known aliases
    best_score = 0
    best_canonical = None
    for alias_lower, canonical in lookup.items():
        score = fuzz.ratio(key, alias_lower)
        if score > best_score:
            best_score = score
            best_canonical = canonical

    if best_score >= _FUZZY_THRESHOLD and best_canonical:
        return best_canonical

    return stripped


def normalize_entities(entities: dict) -> dict:
    """Normalize all entities in an LLM extraction result.

    Args:
        entities: {"persons": [...], "organizations": [...], "technologies": [...], ...}

    Returns:
        Same structure with normalized names, duplicates removed.
    """
    if not entities or not isinstance(entities, dict):
        return entities

    result = {}
    for category, items in entities.items():
        if not isinstance(items, list):
            result[category] = items
            continue

        normalized = []
        seen = set()
        for item in items:
            if not isinstance(item, str):
                continue
            canonical = normalize_entity(item, category)
            if canonical.lower() not in seen:
                seen.add(canonical.lower())
                normalized.append(canonical)

        result[category] = normalized

    return result

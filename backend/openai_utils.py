"""Shared OpenAI credential validation helpers."""

from __future__ import annotations

import logging


logger = logging.getLogger(__name__)
_PLACEHOLDER_MARKERS = ("your", "test", "placeholder", "fake", "dummy", "xxx", "change", "replace")


def is_placeholder_api_key(key: str | None) -> bool:
    """Return whether *key* is clearly absent, synthetic, or unusable.

    The check strips whitespace and is case-insensitive. It rejects ``None``,
    empty values, values without an ``sk-`` prefix, ``sk-`` values shorter
    than 20 characters, keys containing common placeholder markers
    (``your``, ``test``, ``placeholder``, ``fake``, ``dummy``, ``xxx``,
    ``change``, or ``replace``), and repeated-character keys such as
    ``sk-xxxxxxx``. Real OpenAI keys are typically ``sk-proj-...`` and
    substantially longer (usually 40+ characters).
    """
    normalized = (key or "").strip().lower()
    if not normalized or not normalized.startswith("sk-"):
        return True
    if len(normalized) < 20:
        return True
    suffix = normalized[3:]
    if any(marker in suffix for marker in _PLACEHOLDER_MARKERS):
        return True
    if len(suffix) > 10 and len(set(suffix)) == 1:
        return True
    return False


def configured_api_key() -> str | None:
    """Read and validate an API key, logging when placeholder fallback applies."""
    import os

    key = os.getenv("OPENAI_API_KEY")
    if is_placeholder_api_key(key):
        if key and key.strip():
            logger.info("检测到占位或无效 API Key，使用关键词回退")
        return None
    return key.strip()

"""The one place repairs ask a language model for text (spec v0.5.0, "Suggestions and
LLM use"). It never raises: when no LLM is available, too slow or returns nothing
usable, the caller gets None and uses its rule-based fallback.

The LLM client itself is llm.py (shared module, owned by Person 4). This file only
needs llm.py to provide these functions; each returns plain text, or None:

    suggest_title(page_text: str, file_name: str) -> str | None

Until llm.py exists (or when LLM_ENABLED=false), every call returns None and the
rule-based fallback is used, so the service and the tests work without an LLM.
"""

from __future__ import annotations

import importlib
import logging
import os
import re

log = logging.getLogger("pdf_accessibility.remediation.ai")

MAX_PAGE_TEXT_CHARS = 4000  # what is sent to the model for a title (page 1 only)
MAX_TITLE_CHARS = 120


def llm_enabled() -> bool:
    return os.environ.get("LLM_ENABLED", "true").lower() not in ("0", "false", "no")


def _client():
    """The shared llm.py module, or None if it is not there or switched off."""
    if not llm_enabled():
        return None
    try:
        return importlib.import_module("llm")
    except ImportError:
        return None


def clean_title(text: str | None) -> str | None:
    """One line, no surrounding quotes or "Title:" prefix, sensible length."""
    if not text:
        return None
    line = text.strip().splitlines()[0] if text.strip() else ""
    line = re.sub(r"^\s*(?:suggested\s+)?title\s*:\s*", "", line, flags=re.IGNORECASE)
    line = re.sub(r"\s+", " ", line).strip().strip("\"'“”‘’`*").strip()
    if len(line) < 3 or len(line) > MAX_TITLE_CHARS:
        return None
    return line


def suggest_title(page_text: str, file_name: str) -> str | None:
    """An LLM-suggested title for the document, or None (use the fallback)."""
    client = _client()
    fn = getattr(client, "suggest_title", None) if client is not None else None
    if fn is None or not page_text.strip():
        return None
    try:
        return clean_title(fn(page_text[:MAX_PAGE_TEXT_CHARS], file_name))
    except Exception:  # an LLM problem is never a request failure (spec v0.5.0)
        log.warning("llm suggest_title failed; using fallback", exc_info=True)
        return None


def available() -> bool:
    """True when an llm.py client is installed and enabled."""
    return _client() is not None

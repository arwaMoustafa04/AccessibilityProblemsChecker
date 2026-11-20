"""The one place repairs ask a language model for text (spec v0.5.0, "Suggestions and
LLM use"). It never raises: when no LLM is available, too slow or returns nothing
usable, the caller gets None and uses its rule-based fallback.

The LLM client itself is llm.py (configuration, limits, cache, HTTP). It provides
these functions; each returns plain text, or None:

    suggest_title(page_text, file_name)            CHK-TITLE
    describe_image(image_bytes, nearby_text, mime) CHK-NONTEXT  (or "DECORATIVE")
    suggest_link_text(sentence, url)               CHK-LINK
    rewrite_sentence(sentence, problem)            CHK-COLOR ("color"), CHK-SENSORY ("sensory")

When no API key is set (and LLM_MOCK is off), or LLM_ENABLED=false, every call
returns None and the rule-based fallback is used, so the service and the tests work
without an LLM.
"""

from __future__ import annotations

import importlib
import logging
import os
import re
from collections.abc import Iterator
from contextlib import contextmanager, nullcontext

log = logging.getLogger("pdf_accessibility.remediation.ai")

MAX_PAGE_TEXT_CHARS = 4000  # what is sent to the model for a title (page 1 only)
MAX_TITLE_CHARS = 120
MAX_ALT_CHARS = 300
MAX_LINK_CHARS = 100
MAX_SENTENCE_CHARS = 500
DECORATIVE = "DECORATIVE"


def llm_enabled() -> bool:
    return os.environ.get("LLM_ENABLED", "true").lower() not in ("0", "false", "no")


def _client():
    """The shared llm.py module, or None if it is missing, switched off or has no key."""
    if not llm_enabled():
        return None
    try:
        client = importlib.import_module("llm")
    except ImportError:
        return None
    configured = getattr(client, "is_configured", None)
    if callable(configured) and not configured():
        return None
    return client


@contextmanager
def request_budget() -> Iterator[None]:
    """Limits model time and calls for one uploaded PDF (llm.request_budget)."""
    client = _client()
    budget = getattr(client, "request_budget", None) if client is not None else None
    with budget() if callable(budget) else nullcontext():
        yield


def _clean_text(text: str | None, max_chars: int, one_line: bool = True) -> str | None:
    if not text:
        return None
    text = text.strip()
    if one_line:
        text = text.splitlines()[0] if text else ""
    text = re.sub(r"\s+", " ", text).strip().strip("\"'“”‘’`*").strip()
    if len(text) < 2 or len(text) > max_chars:
        return None
    return text


def _call(name: str, *args: object) -> str | None:
    client = _client()
    fn = getattr(client, name, None) if client is not None else None
    if fn is None:
        return None
    try:
        result = fn(*args)
    except Exception:  # an LLM problem is never a request failure (spec v0.5.0)
        log.warning("llm %s failed; using fallback", name, exc_info=True)
        return None
    return result if isinstance(result, str) else None


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
    if not page_text.strip():
        return None
    return clean_title(_call("suggest_title", page_text[:MAX_PAGE_TEXT_CHARS], file_name))


def describe_image(image_bytes: bytes, nearby_text: str = "",
                   mime_type: str = "image/png") -> str | None:
    """AI alt text for an image, DECORATIVE for a decorative one, or None."""
    text = _clean_text(_call("describe_image", image_bytes, nearby_text, mime_type),
                       MAX_ALT_CHARS, one_line=False)
    if text and text.rstrip(".").upper() == DECORATIVE:
        return DECORATIVE
    if text and re.match(r"^(?:an?\s+)?(?:image|picture|photo)\s+of\s+", text, re.I):
        text = re.sub(r"^(?:an?\s+)?(?:image|picture|photo)\s+of\s+", "", text, flags=re.I)
        text = text[:1].upper() + text[1:]
    return text


def suggest_link_text(sentence: str, url: str) -> str | None:
    """AI link text ("Apply for financial aid") for an unclear link, or None."""
    if not sentence.strip():
        return None
    return _clean_text(_call("suggest_link_text", sentence, url), MAX_LINK_CHARS)


def rewrite_sentence(sentence: str, problem: str) -> str | None:
    """AI rewrite of a sentence with a "color" or "sensory" problem, or None."""
    if not sentence.strip() or problem not in ("color", "sensory"):
        return None
    text = _clean_text(_call("rewrite_sentence", sentence, problem), MAX_SENTENCE_CHARS)
    return text if text and text.strip().lower() != sentence.strip().lower() else None


def sends_data() -> bool:
    """True when AI calls go to an external provider (configured, not mock mode)."""
    client = _client()
    mock = getattr(client, "mock_mode", None) if client is not None else None
    return client is not None and not (callable(mock) and mock())


def available() -> bool:
    """True when the LLM client is enabled and configured (API key, or mock mode)."""
    return _client() is not None

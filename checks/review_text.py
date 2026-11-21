"""Shared, page-aware English text heuristics; no OCR and no semantic verdicts."""

import re
from collections.abc import Iterator

from checks.base import CheckContext

# Words that are rarely anything but colors ("gold", "silver", "tan" are left out).
COLORS = (r"(?:red|green|blue|yellow|orange|purple|pink|brown|black|white|gr[ae]y|navy|"
          r"maroon|teal|crimson|scarlet|burgundy|magenta|cyan|violet|indigo|turquoise|"
          r"lavender|olive)")
ACTION = re.compile(r"\b(?:click|select|press|choose|follow|use|complete|enter|refer|see|look|find)\b", re.I)
COLOR_WORD = re.compile(rf"\b{COLORS}\b", re.I)


def blocks(ctx: CheckContext) -> Iterator[tuple[int, int, str]]:
    """All pages, not the capped heading helper. Join wrapped lines within a block."""
    for page_index in range(len(ctx.doc)):
        page = ctx.doc[page_index]
        for index, block in enumerate(page.get_text("blocks")):
            if len(block) > 6 and block[6] != 0:
                continue
            text = " ".join(str(block[4]).split())
            if text:
                yield page.number + 1, index, text


def excerpt(text: str) -> str:
    return text if len(text) <= 240 else text[:237] + "..."


# --- Sentence rewrites (suggested_text for CHK-COLOR / CHK-SENSORY) ------------------
# The cue phrase ("the green button", "the option on the right") is replaced with a
# bracketed placeholder the author fills in, e.g. "Select the [button label]."

_DRAFT_ACTION = re.compile(r"\b(?:click|select|press|choose|tap|use|follow|open|enter|complete|"
                           r"fill in|fill out|look for|listen for|wait for|identify)\b", re.I)
_CONTROL = (r"(?:button|link|field|option|icon|box|arrow|tab|item|form|line|route|"
            r"circle|square|triangle|symbol|section)s?\b")
COLOR_CUE = re.compile(r"\b(?:" + COLORS + r"\s+" + _CONTROL + r"|" + _CONTROL
                       + r"\s+(?:(?:highlighted|shown|marked)\s+)?in\s+" + COLORS + r"\b)", re.I)
SENSORY_CUE = re.compile(
    r"\b(?:(?:round|square|triangular|circular|large|small|leftmost|rightmost|upper|lower|top|"
    r"bottom|left|right)\s+" + _CONTROL + r"|" + _CONTROL
    + r"\s+(?:on|at|to)\s+(?:the\s+)?(?:left|right|top|bottom)\b|"
    r"(?:option|button|link|field|section)\s+(?:above|below)\b|(?:beep|chime|tone)\b)", re.I)
# Already named ("the green button labeled Continue"): no placeholder rewrite needed.
_NAMED = re.compile(r"""\b(?:label(?:l)?ed|named|titled|called)\s+\S|["“‘][^"”’]+["”’]""", re.I)


def sentences(text: str) -> list[str]:
    return [s for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]


def rewrite_draft(text: str, cue: re.Pattern) -> tuple[str, str] | None:
    """(sentence, rule-based rewrite) for the first instruction in `text` that uses `cue`."""
    for sentence in sentences(text):
        action = _DRAFT_ACTION.search(sentence)
        if not action or _NAMED.search(sentence):
            continue
        match = cue.search(sentence, action.end())
        if not match:
            continue
        noun = re.search(_CONTROL, match[0], re.I)
        placeholder = f"[{noun[0].lower()} label]" if noun else "[named indicator]"
        return sentence, sentence[:match.start()] + placeholder + sentence[match.end():]
    return None


def cue_sentence(text: str, *patterns: re.Pattern) -> str:
    """The sentence containing the first cue, for an AI rewrite (else the excerpt)."""
    for sentence in sentences(text):
        if any(p.search(sentence) for p in patterns):
            return sentence[:500]
    return excerpt(text)

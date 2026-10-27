"""Shared, page-aware English text heuristics; no OCR and no semantic verdicts."""

import re
from collections.abc import Iterator

from checks.base import CheckContext

COLORS = r"(?:red|green|blue|yellow|orange|purple|pink|brown|black|white|gr[ae]y)"
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

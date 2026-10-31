"""Rendered-text analysis with PyMuPDF (font sizes, bold, text per page)."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

import pymupdf

BOLD_FLAG = 16  # PyMuPDF span flag bit for bold


@dataclass(frozen=True)
class TextLine:
    page: int  # 1-based
    text: str
    size: float  # largest font size in the line
    bold: bool


def lines(doc: pymupdf.Document, max_pages: int = 300) -> list[TextLine]:
    out = []
    for index in range(min(len(doc), max_pages)):
        page = doc[index]
        for block in page.get_text("dict").get("blocks", []):
            for line in block.get("lines", []):
                spans = [s for s in line.get("spans", []) if s.get("text", "").strip()]
                if not spans:
                    continue
                text = " ".join(s["text"].strip() for s in spans)
                out.append(TextLine(
                    page=index + 1,
                    text=text,
                    size=round(max(s["size"] for s in spans), 1),
                    bold=all(s["flags"] & BOLD_FLAG for s in spans),
                ))
    return out


def body_font_size(all_lines: list[TextLine]) -> float | None:
    """The most common font size, weighted by characters (the body text size)."""
    sizes: Counter[float] = Counter()
    for ln in all_lines:
        sizes[ln.size] += len(ln.text)
    return sizes.most_common(1)[0][0] if sizes else None


def probable_headings(all_lines: list[TextLine]) -> list[TextLine]:
    """Short lines that look like headings: clearly larger than body text, or bold
    and at least body size. A heuristic: results are for human review only."""
    body = body_font_size(all_lines)
    if body is None:
        return []
    found = []
    for ln in all_lines:
        words = len(ln.text.split())
        if not (1 <= words <= 15) or len(ln.text) > 120 or ln.text.endswith((".", ",", ";")):
            continue
        if ln.size >= body * 1.2 or (ln.bold and ln.size >= body and words <= 10):
            found.append(ln)
    return found




def pages_with_text(doc: pymupdf.Document, max_pages: int = 300) -> int:
    return sum(1 for i in range(min(len(doc), max_pages)) if doc[i].get_text("text").strip())

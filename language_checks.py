"""Locate English cue-dependent instructions and generic PDF link annotations."""
from __future__ import annotations

import io
import re
from dataclasses import dataclass
from urllib.parse import unquote, urlsplit

import pikepdf
from pdfminer.high_level import extract_pages
from pdfminer.layout import LAParams, LTChar, LTContainer, LTTextBox, LTTextLine
from pdfminer.pdfexceptions import PDFException

from pdf_checks import Inspector, Issue

GENERIC = re.compile(r"(?:click(?: here)?|here|read more|learn more|more info(?:rmation)?|this link)", re.I)
ACTION = re.compile(r"\b(click|select|press|choose|tap|use|follow|open|enter|complete|fill in|fill out|"
                    r"look for|listen for|wait for|identify)\b", re.I)
CONTROL = (r"(?:button|link|field|option|icon|box|arrow|tab|item|form|line|route|"
           r"circle|square|triangle|symbol|section)s?\b")
COLORS = r"(?:red|green|blue|yellow|orange|purple|pink|black|white|gray|grey)"
COLOR = re.compile(r"\b(?:" + COLORS + r"\s+" + CONTROL + r"|" + CONTROL +
                   r"\s+(?:(?:highlighted|shown|marked)\s+)?in\s+" + COLORS + r"\b)", re.I)
SENSORY = re.compile(r"\b(?:(?:round|square|triangular|large|small|leftmost|rightmost|upper|lower|top|"
                     r"bottom|left|right)\s+" + CONTROL + r"|" + CONTROL +
                     r"\s+(?:on|at|to)\s+(?:the\s+)?(?:left|right|top|bottom)\b|"
                     r"(?:option|button|link|field|section)\s+(?:above|below)\b|"
                     r"(?:beep|chime|tone)\b)", re.I)
NAMED = re.compile(r"""\b(?:label(?:l)?ed|named|titled|called)\s+\S|["“‘][^"”’]+["”’]""", re.I)


@dataclass
class Candidate:
    issue: Issue
    original: str
    context: str
    fallback: str
    destination: str = ""
    annotation_index: int | None = None


def sentence_candidates(text, page, block):
    for n, sentence in enumerate(re.split(r"(?<=[.!?])\s+", text)):
        action = ACTION.search(sentence)
        if not action or NAMED.search(sentence):
            continue
        for check, cue in (("CHK-COLOR", COLOR), ("CHK-SENSORY", SENSORY)):
            match = cue.search(sentence, action.end())
            if not match:
                continue
            noun = re.search(CONTROL, match[0], re.I)
            placeholder = f"[{noun[0].lower()} label]" if noun else "[named status indicator]"
            fallback = sentence[:match.start()] + placeholder + sentence[match.end():]
            issue = Issue(check, "color_dependent_instruction" if check == "CHK-COLOR"
                          else "sensory_dependent_instruction", f"Page[{page}]/Text[{block},{n}]",
                          f'Instruction uses a {check[4:].lower()} cue: “{sentence}”', page, "needs_review")
            yield Candidate(issue, sentence, text[:600], fallback)


def text_boxes(layout):
    for item in layout:
        if isinstance(item, LTTextBox):
            yield item
        elif isinstance(item, LTContainer):
            yield from text_boxes(item)


def annotation_rect(page, rect):
    # pdfminer translates the media-box origin and applies page rotation.
    x0, y0, x1, y1 = map(float, page.mediabox)
    a, b, c, d = map(float, rect)
    rotation = int(page.obj.get("/Rotate", 0)) % 360
    if rotation == 90:
        return b-y0, x1-c, d-y0, x1-a
    if rotation == 180:
        return x1-c, y1-d, x1-a, y1-b
    if rotation == 270:
        return y1-d, a-x0, y1-b, c-x0
    return a-x0, b-y0, c-x0, d-y0


def link_text(boxes, rect):
    left, bottom, right, top = rect
    selected, context = [], []
    for box in boxes:
        hits = []
        before, after = [], []
        seen_hit = False
        for line in box:
            if not isinstance(line, LTTextLine):
                continue
            piece = ""
            for glyph in line:
                value = glyph.get_text()
                if isinstance(glyph, LTChar):
                    x, y = (glyph.x0 + glyph.x1)/2, (glyph.y0 + glyph.y1)/2
                    if left <= x <= right and bottom <= y <= top:
                        piece += value
                        seen_hit = True
                        continue
                elif piece and value.isspace():
                    piece += " "
                (after if seen_hit else before).append(value)
            if piece.strip():
                hits.append(piece.strip())
        if hits:
            selected.extend(hits)
            # Isolate this occurrence even when a paragraph contains several identical links.
            prefix = re.split(r"(?<=[.!?])\s+", "".join(before))[-1][-200:]
            suffix = re.split(r"(?<=[.!?])\s+", "".join(after), maxsplit=1)[0][:200]
            context.append(" ".join((prefix + " " + " ".join(hits) + suffix).split()))
    return " ".join(selected), " ".join(context)


def destination_hint(annotation, pages):
    action = annotation.get("/A")
    dest = annotation.get("/Dest")
    if isinstance(action, pikepdf.Dictionary):
        dest = action.get("/D", dest)
        if action.get("/S") == pikepdf.Name.URI:
            try:
                uri = urlsplit(str(action.get("/URI", "")))
                if uri.scheme.lower() in {"http", "https"} and uri.hostname:
                    return (uri.hostname + uri.path)[:160]
            except ValueError:
                pass
    if isinstance(dest, pikepdf.Array) and len(dest) and isinstance(dest[0], pikepdf.Dictionary):
        number = pages.get(dest[0].objgen)
        if number:
            return f"page {number}"
    return ""


def fallback_label(text, hint):
    purpose = re.search(r"\b[Tt]o ([\w '-]{3,70}),\s*(?:please\s+)?click here\b", text)
    if purpose:
        return purpose[1][:1].upper() + purpose[1][1:]
    if hint.startswith("page "):
        return f"Go to {hint}"
    if hint:
        host, _, path = hint.partition("/")
        name = re.sub(r"[-_]+", " ", unquote(path.rstrip("/").split("/")[-1]))
        if name and re.fullmatch(r"[\w ]{2,64}", name):
            return f"Open {name} on {host}"
        return f"Open link to {host}"
    return "Open linked destination"


def link_index(pdf):
    inspector = Inspector(pdf)
    inspector.structure()
    return inspector.link_tags


def collect(pdf, data):
    candidates: list[Candidate] = []
    limitations: list[str] = []
    tags = link_index(pdf)
    pages = {page.obj.objgen: n for n, page in enumerate(pdf.pages, 1)}
    try:
        layouts = extract_pages(io.BytesIO(data), laparams=LAParams(all_texts=True))
        for number, layout in enumerate(layouts, 1):
            page = pdf.pages[number - 1]
            boxes = list(text_boxes(layout))
            if not boxes:
                limitations.append(f"Page {number}: no extractable English text for wording checks.")
            for block, box in enumerate(boxes):
                candidates.extend(sentence_candidates(" ".join(box.get_text().split()), number, block))
            annots = page.obj.get("/Annots")
            if not isinstance(annots, pikepdf.Array):
                continue
            for index, annot in enumerate(annots):
                if not isinstance(annot, pikepdf.Dictionary) or annot.get("/Subtype") != pikepdf.Name.Link:
                    continue
                tag = tags.get(annot.objgen)
                labels = [annot.get("/Contents"), tag.get("/Alt") if tag is not None else None]
                if any(isinstance(v, pikepdf.String) and str(v).strip() and
                       not GENERIC.fullmatch(str(v).strip(" .!?")) for v in labels):
                    continue
                try:
                    rect = annotation_rect(page, annot.get("/Rect", []))
                except (TypeError, ValueError):
                    continue
                visible, context = link_text(boxes, rect)
                if not GENERIC.fullmatch(visible.strip(" .!?")):
                    continue
                hint = destination_hint(annot, pages)
                issue = Issue("CHK-LINK", "generic_link_text", f"Page[{number}]/Annots[{index}]",
                              f'Link text “{visible}” needs a descriptive accessible label',
                              number, "needs_review")
                label = fallback_label(context, hint)
                candidates.append(Candidate(issue, visible, context, label, hint, index))
    except (PDFException, ValueError, TypeError, OverflowError, RecursionError):
        limitations.append("Text extraction was incomplete. Review remaining links and instructions.")
    return candidates, tags, limitations

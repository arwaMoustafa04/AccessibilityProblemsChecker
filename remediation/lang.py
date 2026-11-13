"""Repairs for CHK-LANG (WCAG 3.1.1 Language of Page, auto_fixable). No AI is used.

Document language (catalog /Lang), in order:
  1. a broken tag that can be corrected: "en_US" -> "en-US", "EN-us" -> "en-US",
     "English" -> "en"
  2. the language detected from the document's text (langdetect, offline)
  3. en-US, when there is too little text to detect a language (noted as assumed)

A structure element with an invalid /Lang gets the corrected tag, or, when it
cannot be corrected, loses its /Lang so it uses the document language.
"""

from __future__ import annotations

import re

import pikepdf

from checks.base import Issue
from checks.lang import is_valid_language
from remediation import RepairAction, RepairContext, repairer

CHECK_ID = "CHK-LANG"
DEFAULT_LANGUAGE = "en-US"
MAX_TEXT_CHARS = 5000  # enough to detect a language reliably
MIN_LETTERS = 40  # below this, detection is a guess, so the default is used
MIN_CONFIDENCE = 0.80

# ISO 639-1 language codes: a corrected tag must start with a real language.
ISO_639_1 = frozenset("""
aa ab ae af ak am an ar as av ay az ba be bg bh bi bm bn bo br bs ca ce ch co cr cs cu
cv cy da de dv dz ee el en eo es et eu fa ff fi fj fo fr fy ga gd gl gn gu gv ha he hi
ho hr ht hu hy hz ia id ie ig ii ik io is it iu ja jv ka kg ki kj kk kl km kn ko kr ks
ku kv kw ky la lb lg li ln lo lt lu lv mg mh mi mk ml mn mr ms mt my na nb nd ne ng nl
nn no nr nv ny oc oj om or os pa pi pl ps pt qu rm rn ro ru rw sa sc sd se sg si sk sl
sm sn so sq sr ss st su sv sw ta te tg th ti tk tl tn to tr ts tt tw ty ug uk ur uz ve
vi vo wa wo xh yi yo za zh zu
""".split())

_NAMES = {
    "english": "en", "spanish": "es", "español": "es", "french": "fr", "français": "fr",
    "german": "de", "deutsch": "de", "arabic": "ar", "chinese": "zh", "japanese": "ja",
    "korean": "ko", "italian": "it", "portuguese": "pt", "russian": "ru", "hindi": "hi",
    "dutch": "nl", "turkish": "tr", "vietnamese": "vi", "polish": "pl",
}


def correct_tag(tag: str) -> str | None:
    """A valid BCP 47 tag for a slightly broken one, or None."""
    raw = tag.strip()
    if raw.lower() in _NAMES:
        return _NAMES[raw.lower()]
    parts = [p for p in re.split(r"[-_\s]+", raw) if p]
    if not parts or parts[0].lower() not in ISO_639_1 or len(parts) > 3:
        return None
    fixed = [parts[0].lower()]
    for part in parts[1:]:  # only script and region subtags are corrected
        if re.fullmatch(r"[A-Za-z]{4}", part) and len(fixed) == 1:
            fixed.append(part.title())  # script: Latn, Hans
        elif re.fullmatch(r"[A-Za-z]{2}|\d{3}", part):
            fixed.append(part.upper())  # region: US, MX, 419
        else:
            return None
    candidate = "-".join(fixed)
    return candidate if is_valid_language(candidate) else None


def _document_text(rctx: RepairContext) -> str:
    chunks, size = [], 0
    try:
        doc = rctx.check.doc
        for index in range(len(doc)):
            text = doc[index].get_text("text")
            chunks.append(text)
            size += len(text)
            if size >= MAX_TEXT_CHARS:
                break
    except Exception:
        return ""
    return "".join(chunks)[:MAX_TEXT_CHARS]


def detect_language(text: str) -> str | None:
    """The language of `text` as a BCP 47 tag, or None if it cannot be told reliably."""
    if sum(ch.isalpha() for ch in text) < MIN_LETTERS:
        return None
    try:
        from langdetect import DetectorFactory, detect_langs
        from langdetect.lang_detect_exception import LangDetectException
    except ImportError:
        return None
    DetectorFactory.seed = 0  # same answer for the same text every time
    try:
        best = detect_langs(text)[0]
    except LangDetectException:
        return None
    if best.prob < MIN_CONFIDENCE:
        return None
    code = str(best.lang)
    if "-" in code:  # langdetect writes zh-cn / zh-tw
        lang, region = code.split("-", 1)
        code = f"{lang}-{region.upper()}"
    return code if is_valid_language(code) else None


def choose_language(rctx: RepairContext, current: str) -> tuple[str, str]:
    """(tag, how it was chosen), computed once per document."""
    cached = rctx.shared.get("lang")
    if isinstance(cached, tuple):
        return cached  # type: ignore[return-value]
    corrected = correct_tag(current) if current else None
    if corrected:
        chosen = (corrected, f'corrected from "{current}"')
    else:
        detected = detect_language(_document_text(rctx))
        if detected:
            chosen = (detected, "detected from the document text")
        else:
            chosen = (DEFAULT_LANGUAGE, "assumed; too little text to detect the language")
            rctx.note("CHK-LANG: the document language could not be detected (too little "
                      f"text), so {DEFAULT_LANGUAGE} was assumed; please verify it.")
    rctx.shared["lang"] = chosen
    return chosen


@repairer(CHECK_ID, "missing_document_language", "invalid_document_language")
def set_document_language(issue: Issue, rctx: RepairContext) -> RepairAction:
    current = str(rctx.pdf.Root.get("/Lang", "")).strip()
    tag, how = choose_language(rctx, current)
    rctx.pdf.Root.Lang = pikepdf.String(tag)
    return RepairAction(f'Set the document language to "{tag}" ({how})', applied_text=tag)


def _object(pdf: pikepdf.Pdf, ref: str | None) -> pikepdf.Object | None:
    match = re.fullmatch(r"(\d+) (\d+) R", ref or "")
    if not match:
        return None
    try:
        return pdf.get_object((int(match[1]), int(match[2])))
    except Exception:
        return None


@repairer(CHECK_ID, "invalid_element_language")
def fix_element_language(issue: Issue, rctx: RepairContext) -> RepairAction | None:
    elem = _object(rctx.pdf, issue.object_ref)
    if not isinstance(elem, pikepdf.Dictionary) or "/Lang" not in elem:
        return None
    current = str(elem.get("/Lang", "")).strip()
    corrected = correct_tag(current)
    if corrected:
        elem.Lang = pikepdf.String(corrected)
        return RepairAction(f'Changed the passage language "{current}" to "{corrected}"',
                            applied_text=corrected)
    del elem["/Lang"]
    return RepairAction(f'Removed the invalid passage language "{current}", so the passage '
                        "uses the document language")

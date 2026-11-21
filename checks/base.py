"""Shared types for the accessibility checks.

Every check is a function ``check(ctx) -> list[Issue]``. It only *detects*; the
classification (auto_fixable / human_review) and WCAG data come from catalog.py,
so a check cannot contradict the agreed catalog.
"""

from __future__ import annotations

import io
from dataclasses import dataclass, field
from functools import cached_property
from typing import TYPE_CHECKING, Literal

import pikepdf
import pymupdf

if TYPE_CHECKING:
    from checks.verapdf import VeraReport


@dataclass
class Issue:
    """One problem found by a check (becomes one Finding in the response)."""

    check_id: str
    issue_type: str  # short snake_case name, e.g. "missing_document_title"
    description: str  # what is wrong, in plain words (Location.description)
    evaluation_result: Literal["fail", "needs_review"] = "fail"
    page: int | None = None  # 1-based page number, when the issue is on a page
    object_ref: str | None = None  # where in the PDF, e.g. "Catalog/Lang" or "12 0 R"
    suggestion: str | None = None  # how it can be fixed (Finding.fix_description)
    sources: list[str] = field(default_factory=list)  # tools that found it, e.g. ["pikepdf"]
    # [x0, y0, x1, y1] on `page` in PDF user space; filled by checks/locate.py if not set here
    bbox: list[float] | None = None
    # Concrete proposed text for the fix (alt text, link text, a title, a heading level),
    # and who wrote it: "rule" (template/fixed text) or "llm" (spec v0.5.0, optional).
    suggested_text: str | None = None
    suggestion_source: Literal["rule", "llm"] | None = None
    # The source text the issue is about (a link's sentence, a flagged instruction).
    # Used by repairs and AI suggestions; not part of the response.
    evidence: str | None = None

    @property
    def key(self) -> tuple:
        """Identity used to match an issue before and after repair (same type, same place)."""
        return self.check_id, self.issue_type, self.page, self.object_ref


@dataclass
class CheckContext:
    """The uploaded PDF, opened once and shared by every check.

    - ``pdf``: pikepdf view (objects, catalog, metadata, structure tree)
    - ``doc``: PyMuPDF view (rendered text, fonts, sizes, images, links)
    - ``verapdf``: veraPDF PDF/UA-1 report, run once on first use (None if unavailable)
    """

    data: bytes
    file_name: str
    pdf: pikepdf.Pdf

    @cached_property
    def doc(self) -> pymupdf.Document:
        return pymupdf.open(stream=self.data, filetype="pdf")

    @cached_property
    def text_pages(self) -> set[int]:
        """Invisible OCR text counts; whitespace alone does not."""
        return {n + 1 for n in range(len(self.doc)) if self.doc[n].get_text("text").strip()}

    @cached_property
    def scanned_pages(self) -> set[int]:
        # get_image_info sees drawn inline and nested images, not unused resources.
        return {n + 1 for n in range(len(self.doc))
                if n + 1 not in self.text_pages and self.doc[n].get_image_info()}

    @cached_property
    def verapdf(self) -> VeraReport:
        from checks.verapdf import run_verapdf
        return run_verapdf(self.data)

    @cached_property
    def tag_issues(self) -> list[Issue]:
        """CHK-NONTEXT and CHK-STRUCTURE issues from pdf_checks.py, inspected once for both."""
        from pdf_checks import detect_pdf_issues
        return [Issue(i.check_id, i.issue_type, i.description, i.evaluation_result,
                      page=i.page, object_ref=i.object_ref, sources=["pikepdf"])
                for i in detect_pdf_issues(self.pdf)]

    @cached_property
    def page_numbers(self) -> dict[tuple[int, int], int]:
        """Page object (objgen) -> 1-based page number, for /Pg and /P references."""
        return {page.obj.objgen: n for n, page in enumerate(self.pdf.pages, start=1)}

    def page_of(self, obj: object) -> int | None:
        try:
            return self.page_numbers.get(obj.objgen)  # type: ignore[attr-defined]
        except AttributeError:
            return None

    def close(self) -> None:
        if "doc" in self.__dict__:
            self.doc.close()


def open_copy(data: bytes) -> pikepdf.Pdf:
    """Open a separate pikepdf copy (used for re-validation after repairs)."""
    return pikepdf.open(io.BytesIO(data))

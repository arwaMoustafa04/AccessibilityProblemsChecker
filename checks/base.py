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

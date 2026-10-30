"""PDF evaluation pipeline behind POST /process.

Stages (shared spec, POST /process description):
RECEIVED -> VALIDATED -> EVALUATED -> CLASSIFIED -> REPAIRED -> REVALIDATED -> REPORTED

CHK-NONTEXT and CHK-STRUCTURE run by default and produce human-review findings.
Title/language detection and repair remain opt-in via ENABLE_TITLE_LANG_CHECKS.
"""

from __future__ import annotations

import base64
import hashlib
import io
import os
import uuid
from pathlib import PurePath

import pikepdf

from catalog import CHECKS_BY_ID
from models import (
    ErrorCode,
    EvaluationResult,
    Finding,
    FindingStatus,
    Location,
    OutputFile,
    Repair,
)
from pdf_checks import Issue, detect_pdf_issues

MAX_FILE_SIZE_BYTES = 20_971_520
DEFAULT_LANGUAGE = "en-US"

# Title/language automatic repair remains off by default.
ENABLE_TITLE_LANG_CHECKS = os.environ.get("ENABLE_TITLE_LANG_CHECKS", "").lower() in (
    "1", "true", "yes")

IMPLEMENTED_CHECKS = ["CHK-NONTEXT", "CHK-STRUCTURE"]
TITLE_LANG_CHECKS = ["CHK-TITLE", "CHK-LANG"]
NOT_YET_IMPLEMENTED = [
    "CHK-SENSORY",
    "CHK-COLOR", "CHK-LINK", "CHK-HEADINGS",
]


class PipelineError(Exception):
    """An expected project error; maps to one of the spec's error responses."""

    def __init__(self, http_status: int, error_code: ErrorCode, message: str):
        super().__init__(message)
        self.http_status = http_status
        self.error_code = error_code
        self.message = message


# --- VALIDATED ---------------------------------------------------------------

def validate_input(data: bytes) -> pikepdf.Pdf:
    if not data:
        raise PipelineError(400, "MISSING_FILE",
                            "Request must include a PDF in the 'file' field.")
    if len(data) > MAX_FILE_SIZE_BYTES:
        raise PipelineError(413, "FILE_TOO_LARGE",
                            "File exceeds the 20 MB project limit.")
    if b"%PDF-" not in data[:1024]:
        raise PipelineError(415, "INVALID_FILE_TYPE", "Input must be a PDF file.")
    try:
        pdf = pikepdf.open(io.BytesIO(data))
    except pikepdf.PasswordError:
        raise PipelineError(422, "PASSWORD_PROTECTED_PDF",
                            "PDF is password-protected and cannot be opened.") from None
    except pikepdf.PdfError:
        raise PipelineError(422, "CORRUPTED_PDF",
                            "PDF is corrupted and cannot be processed.") from None
    if pdf.is_encrypted:
        pdf.close()
        raise PipelineError(422, "ENCRYPTED_PDF",
                            "PDF is encrypted and cannot be processed.")
    try:
        len(pdf.pages)
    except Exception:
        pdf.close()
        raise PipelineError(422, "UNREADABLE_PDF",
                            "PDF page tree cannot be read.") from None
    return pdf


# --- EVALUATED / CLASSIFIED --------------------------------------------------

def _document_title(pdf: pikepdf.Pdf) -> str:
    title = ""
    if "/Title" in pdf.docinfo:
        title = str(pdf.docinfo["/Title"]).strip()
    if not title:
        try:
            with pdf.open_metadata(set_pikepdf_as_editor=False) as meta:
                title = str(meta.get("dc:title", "") or "").strip()
        except Exception:
            title = ""
    return title


def detect_issues(pdf: pikepdf.Pdf) -> list[Issue]:
    issues = detect_pdf_issues(pdf)
    if not ENABLE_TITLE_LANG_CHECKS:
        return issues

    # CHK-TITLE (WCAG 2.4.2): a title exists and viewers are told to show it.
    if not _document_title(pdf):
        issues.append(Issue("CHK-TITLE", "missing_document_title", "Info/Title",
                            "Document title is not set"))
    prefs = pdf.Root.get("/ViewerPreferences")
    display_title = prefs.get("/DisplayDocTitle") if prefs is not None else None
    if display_title is not True:
        issues.append(Issue("CHK-TITLE", "display_doc_title_not_set",
                            "Catalog/ViewerPreferences/DisplayDocTitle",
                            "Viewers are not told to display the document title"))

    # CHK-LANG (WCAG 3.1.1): a document-level language is declared.
    lang = str(pdf.Root.get("/Lang", "")).strip()
    if not lang:
        issues.append(Issue("CHK-LANG", "missing_document_language", "Catalog/Lang",
                            "Document-level language is not set"))
    return issues


# --- REPAIRED ----------------------------------------------------------------

def _title_from_filename(file_name: str) -> str:
    stem = PurePath(file_name).stem.replace("_", " ").replace("-", " ").strip()
    return stem or "Untitled document"


def repair(pdf: pikepdf.Pdf, issues: list[Issue], file_name: str) -> dict[str, str]:
    """Apply supported fixes to this (already copied) PDF; return issue_type -> action."""
    actions: dict[str, str] = {}
    for issue in issues:
        if issue.issue_type == "missing_document_title":
            title = _title_from_filename(file_name)
            pdf.docinfo["/Title"] = title
            with pdf.open_metadata(set_pikepdf_as_editor=False) as meta:
                meta["dc:title"] = title
            actions[issue.issue_type] = f'Set document title to "{title}" (from file name)'
        elif issue.issue_type == "display_doc_title_not_set":
            if "/ViewerPreferences" not in pdf.Root:
                pdf.Root.ViewerPreferences = pikepdf.Dictionary()
            pdf.Root.ViewerPreferences.DisplayDocTitle = True
            actions[issue.issue_type] = "Set ViewerPreferences/DisplayDocTitle to true"
        elif issue.issue_type == "missing_document_language":
            pdf.Root.Lang = pikepdf.String(DEFAULT_LANGUAGE)
            actions[issue.issue_type] = f"Set document language to {DEFAULT_LANGUAGE}"
    return actions


# --- REPORTED ----------------------------------------------------------------

def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def build_report_pdf(result: dict) -> bytes:
    from xml.sax.saxutils import escape

    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=letter, title="Accessibility Report",
                            lang="en-US")
    styles = getSampleStyleSheet()

    def p(text: str, style: str = "BodyText") -> Paragraph:
        return Paragraph(escape(text), styles[style])

    story = [
        p("Accessibility Report", "Title"),
        p(f"File: {result['input']['file_name']}"),
        p(f"SHA-256 of evaluated file: {result['input']['sha256']}"),
        p(f"Evaluation ID: {result['evaluation_id']}"),
        Spacer(1, 8),
        p("Checks performed", "Heading2"),
        p(", ".join(result["checks_performed"]) or "None."),
        p("Findings", "Heading2"),
    ]
    if result["findings"]:
        for f in result["findings"]:
            story.append(p(f"{f['finding_id']} - {f['check_id']} (WCAG {f['wcag_criterion']}): "
                           f"{f['location']['description']}. "
                           f"Page: {f['location']['page'] or 'document'}. "
                           f"Object: {f['location']['object_ref']}. "
                           f"Result: {f['evaluation_result']}. Status: {f['status']}."))
    elif result["checks_performed"]:
        story.append(p("No issues found by the checks performed."))
    else:
        story.append(p("None: no checks were performed."))
    story.append(p("Automatic repairs", "Heading2"))
    if result["repairs"]:
        for r in result["repairs"]:
            story.append(p(f"{r['repair_id']} for {r['finding_id']}: {r['action']}. "
                           f"Re-validation: {r['validation_result']}."))
    else:
        story.append(p("No repairs were applied."))
    story.append(p("Needs human review", "Heading2"))
    story.append(p(", ".join(result["human_review_items"]) or "None."))
    story.append(p("Limitations", "Heading2"))
    for line in result["limitations"]:
        story.append(p(line))
    story.append(Spacer(1, 8))
    story.append(p(result["compliance_statement"]))
    doc.build(story)
    return buf.getvalue()


# --- Whole pipeline ----------------------------------------------------------

def _finding(fid: str, issue: Issue, status: FindingStatus, fix: str | None) -> Finding:
    check = CHECKS_BY_ID[issue.check_id]
    return Finding(
        finding_id=fid,
        check_id=issue.check_id,
        issue_type=issue.issue_type,
        wcag_criterion=check.wcag_criterion,
        wcag_level=check.wcag_level,
        location=Location(page=issue.page, object_ref=issue.object_ref,
                          description=issue.description),
        evaluation_result=issue.evaluation_result,
        classification=check.classification,
        status=status,
        fix_description=fix,
    )


def run_pipeline(data: bytes, file_name: str) -> EvaluationResult:
    file_name = file_name or "upload.pdf"
    pdf = validate_input(data)  # opened from an in-memory copy; `data` is never changed
    try:
        issues = detect_issues(pdf)
        actions = repair(pdf, issues, file_name) if ENABLE_TITLE_LANG_CHECKS else {}
        repaired_bytes = data
        if actions:
            out = io.BytesIO()
            pdf.save(out)
            repaired_bytes = out.getvalue()
    finally:
        pdf.close()

    # REVALIDATED: re-run the implemented checks on the repaired copy.
    remaining = issues
    if actions:
        with pikepdf.open(io.BytesIO(repaired_bytes)) as repaired:
            remaining = detect_issues(repaired)
    remaining_keys = {i.key for i in remaining}
    original_keys = {i.key for i in issues}

    findings: list[Finding] = []
    repairs: list[Repair] = []
    for n, issue in enumerate(issues, start=1):
        fid = f"F-{n}"
        if CHECKS_BY_ID[issue.check_id].classification == "human_review":
            findings.append(_finding(fid, issue, "needs_human_review", None))
            continue
        passed = issue.key not in remaining_keys
        findings.append(_finding(fid, issue, "fixed" if passed else "repair_failed",
                                 actions.get(issue.issue_type)))
        if issue.issue_type in actions:
            repairs.append(Repair(repair_id=f"R-{len(repairs) + 1}", finding_id=fid,
                                  action=actions[issue.issue_type],
                                  validation_result="passed" if passed else "failed"))
    new_issues = [
        _finding(f"N-{n}", i, "needs_human_review"
                 if CHECKS_BY_ID[i.check_id].classification == "human_review" else "repair_failed", None)
        for n, i in enumerate(
            (i for i in remaining if i.key not in original_keys), start=1)
    ]

    stem = PurePath(file_name).stem
    fixed = sum(1 for f in findings if f.status == "fixed")
    review_ids = [f.finding_id for f in findings + new_issues if f.status == "needs_human_review"]
    enabled = IMPLEMENTED_CHECKS + (TITLE_LANG_CHECKS if ENABLE_TITLE_LANG_CHECKS else [])
    disabled = NOT_YET_IMPLEMENTED + ([] if ENABLE_TITLE_LANG_CHECKS else TITLE_LANG_CHECKS)
    result = {
        "evaluation_id": str(uuid.uuid4()),
        "status": "completed",
        "input": {"file_name": file_name, "sha256": _sha256(data), "size_bytes": len(data)},
        "outcome": "completed_with_repairs" if actions else "completed_no_repairs",
        "checks_performed": enabled,
        "findings": [f.model_dump() for f in findings],
        "repairs": [r.model_dump() for r in repairs],
        "new_issues_after_repair": [f.model_dump() for f in new_issues],
        "human_review_items": review_ids,
        "summary": {"total_issues": len(findings), "fixed_count": fixed,
                    "human_review_count": len(review_ids)},
        "limitations": [
            "Checks " + ", ".join(disabled)
            + " were not performed (unimplemented or disabled).",
            "Human-review findings are never repaired automatically.",
            "Image purpose, alternative-text accuracy, reading order, complete tagging, and table "
            "semantics require human review. Untagged tables and vector graphics are not inferred.",
            "A present Alt or TH tag does not establish accessibility or semantic correctness.",
            *([f'Titles are derived from filenames and languages default to "{DEFAULT_LANGUAGE}"; '
               'a person should confirm both.'] if ENABLE_TITLE_LANG_CHECKS else []),
        ],
        "compliance_statement": "This report does not certify ADA Title II or WCAG 2.1 conformance.",
    }
    report_bytes = build_report_pdf(result)
    return EvaluationResult.model_validate({
        **result,
        "output_pdf": OutputFile(file_name=f"{stem}_repaired.pdf", sha256=_sha256(repaired_bytes),
                              modified=bool(actions), content_base64=_b64(repaired_bytes)),
        "report_pdf": OutputFile(file_name=f"{stem}_report.pdf", sha256=_sha256(report_bytes),
                              content_base64=_b64(report_bytes)),
    })

"""PDF evaluation pipeline behind POST /process.

Stages (shared spec, POST /process description):
RECEIVED -> VALIDATED -> EVALUATED -> CLASSIFIED -> REPAIRED -> REVALIDATED -> REPORTED

Phase 3 scope: input validation is complete, and the two auto-fixable checks
(CHK-TITLE, CHK-LANG) are detected, repaired on a copy, and re-validated.
The six human-review checks are not implemented yet (Phase 4); they are left
out of checks_performed and named in limitations, so an empty findings list is
never mistaken for "checked and passed".
"""

from __future__ import annotations

import base64
import hashlib
import io
import uuid
from dataclasses import dataclass
from pathlib import PurePath

import pikepdf

from catalog import CHECKS_BY_ID
from models import (
    EvaluationResult,
    Finding,
    InputFile,
    Location,
    OutputFile,
    Repair,
    Summary,
)

MAX_FILE_SIZE_BYTES = 20_971_520
DEFAULT_LANGUAGE = "en-US"

IMPLEMENTED_CHECKS = ["CHK-TITLE", "CHK-LANG"]
NOT_YET_IMPLEMENTED = [
    "CHK-NONTEXT", "CHK-STRUCTURE", "CHK-SENSORY",
    "CHK-COLOR", "CHK-LINK", "CHK-HEADINGS",
]


class PipelineError(Exception):
    """An expected project error; maps to one of the spec's error responses."""

    def __init__(self, http_status: int, error_code: str, message: str):
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
                            "PDF is password-protected and cannot be opened.")
    except pikepdf.PdfError:
        raise PipelineError(422, "CORRUPTED_PDF",
                            "PDF is corrupted and cannot be processed.")
    if pdf.is_encrypted:
        pdf.close()
        raise PipelineError(422, "ENCRYPTED_PDF",
                            "PDF is encrypted and cannot be processed.")
    try:
        len(pdf.pages)
    except Exception:
        pdf.close()
        raise PipelineError(422, "UNREADABLE_PDF",
                            "PDF page tree cannot be read.")
    return pdf


# --- EVALUATED / CLASSIFIED --------------------------------------------------

@dataclass
class Issue:
    check_id: str
    issue_type: str
    object_ref: str
    description: str


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
    issues: list[Issue] = []

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
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer
    from xml.sax.saxutils import escape

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=letter, title="Accessibility Report",
                            lang="en-US")
    styles = getSampleStyleSheet()
    p = lambda text, style="BodyText": Paragraph(escape(text), styles[style])
    story = [
        p("Accessibility Report", "Title"),
        p(f"File: {result['input']['file_name']}"),
        p(f"SHA-256 of evaluated file: {result['input']['sha256']}"),
        p(f"Evaluation ID: {result['evaluation_id']}"),
        Spacer(1, 8),
        p("Checks performed", "Heading2"),
        p(", ".join(result["checks_performed"])),
        p("Findings", "Heading2"),
    ]
    if result["findings"]:
        for f in result["findings"]:
            story.append(p(f"{f['finding_id']} - {f['check_id']} (WCAG {f['wcag_criterion']}): "
                           f"{f['location']['description']}. Status: {f['status']}."))
    else:
        story.append(p("No issues found by the checks performed."))
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

def _finding(fid: str, issue: Issue, status: str, fix: str | None) -> Finding:
    check = CHECKS_BY_ID[issue.check_id]
    return Finding(
        finding_id=fid,
        check_id=issue.check_id,
        issue_type=issue.issue_type,
        wcag_criterion=check.wcag_criterion,
        wcag_level=check.wcag_level,
        location=Location(page=None, object_ref=issue.object_ref,
                          description=issue.description),
        evaluation_result="fail",
        classification=check.classification,
        status=status,
        fix_description=fix,
    )


def run_pipeline(data: bytes, file_name: str) -> EvaluationResult:
    file_name = file_name or "upload.pdf"
    pdf = validate_input(data)  # opened from an in-memory copy; `data` is never changed
    try:
        issues = detect_issues(pdf)
        actions = repair(pdf, issues, file_name) if issues else {}
        out = io.BytesIO()
        pdf.save(out)
        repaired_bytes = out.getvalue() if actions else data
    finally:
        pdf.close()

    # REVALIDATED: re-run the implemented checks on the repaired copy.
    with pikepdf.open(io.BytesIO(repaired_bytes)) as repaired:
        remaining = detect_issues(repaired)
    remaining_types = {i.issue_type for i in remaining}
    original_types = {i.issue_type for i in issues}

    findings: list[Finding] = []
    repairs: list[Repair] = []
    for n, issue in enumerate(issues, start=1):
        fid = f"F-{n}"
        passed = issue.issue_type not in remaining_types
        findings.append(_finding(fid, issue, "fixed" if passed else "repair_failed",
                                 actions.get(issue.issue_type)))
        repairs.append(Repair(repair_id=f"R-{n}", finding_id=fid,
                              action=actions.get(issue.issue_type, "No supported repair"),
                              validation_result="passed" if passed else "failed"))
    new_issues = [
        _finding(f"N-{n}", i, "repair_failed", None)
        for n, i in enumerate(
            (i for i in remaining if i.issue_type not in original_types), start=1)
    ]

    stem = PurePath(file_name).stem
    fixed = sum(1 for f in findings if f.status == "fixed")
    result = {
        "evaluation_id": str(uuid.uuid4()),
        "status": "completed",
        "input": {"file_name": file_name, "sha256": _sha256(data), "size_bytes": len(data)},
        "outcome": "completed_with_repairs" if actions else "completed_no_repairs",
        "checks_performed": list(IMPLEMENTED_CHECKS),
        "findings": [f.model_dump() for f in findings],
        "repairs": [r.model_dump() for r in repairs],
        "new_issues_after_repair": [f.model_dump() for f in new_issues],
        "human_review_items": [],
        "summary": {"total_issues": len(findings), "fixed_count": fixed,
                    "human_review_count": 0},
        "limitations": [
            "Checks " + ", ".join(NOT_YET_IMPLEMENTED)
            + " are not implemented yet (planned for Phase 4) and were not performed.",
            "Human-review findings are never repaired automatically.",
            f'Missing titles are set from the file name and missing languages are set to '
            f'"{DEFAULT_LANGUAGE}"; a person should confirm both.',
        ],
        "compliance_statement": "This report does not certify ADA Title II or WCAG 2.1 conformance.",
    }
    report_bytes = build_report_pdf(result)
    return EvaluationResult(
        **result,
        output_pdf=OutputFile(file_name=f"{stem}_repaired.pdf", sha256=_sha256(repaired_bytes),
                              modified=bool(actions), content_base64=_b64(repaired_bytes)),
        report_pdf=OutputFile(file_name=f"{stem}_report.pdf", sha256=_sha256(report_bytes),
                              content_base64=_b64(report_bytes)),
    )

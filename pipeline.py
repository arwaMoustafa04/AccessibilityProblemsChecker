"""PDF evaluation pipeline behind POST /process.

Stages (shared spec, POST /process description):
RECEIVED -> VALIDATED -> EVALUATED -> CLASSIFIED -> REPAIRED -> REVALIDATED -> REPORTED

Phase 4 (current): input validation, then every registered check in checks/
(CHK-TITLE, CHK-LANG and CHK-HEADINGS so far; the rest are added by teammates).
Findings are classified from catalog.py. No repairs: auto-fixable findings are
reported with status "detected" and the PDF is returned unchanged. Checks that
are not implemented yet are listed in limitations, so an empty findings list is
never mistaken for "checked and passed".

Automatic repair (Phase 5) is already here but switched OFF. Set the environment
variable ENABLE_REPAIRS=true to try it locally.
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import os
import re
import uuid
import warnings
import zipfile
from pathlib import PurePath

import pikepdf

from catalog import CHECKS_BY_ID
from checks import CheckRun, run_checks
from checks.base import CheckContext, Issue
from models import (
    ErrorCode,
    EvaluationResult,
    Finding,
    FindingStatus,
    Location,
    OutputFile,
    Repair,
)

MAX_FILE_SIZE_BYTES = 20_971_520
DEFAULT_LANGUAGE = "en-US"
COMPLIANCE_STATEMENT = "This report does not certify ADA Title II or WCAG 2.1 conformance."

# Off by default: Phase 4 detects and classifies only. Repair is Phase 5.
ENABLE_REPAIRS = os.environ.get("ENABLE_REPAIRS", "").lower() in ("1", "true", "yes")


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

def evaluate(data: bytes, file_name: str, pdf: pikepdf.Pdf) -> tuple[CheckRun, CheckContext]:
    """Run every registered check (checks/__init__.py) on one opened PDF."""
    ctx = CheckContext(data, file_name, pdf)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")  # pikepdf XMP sync warnings on odd metadata
        run = run_checks(ctx)
    return run, ctx


def _status(issue: Issue) -> FindingStatus:
    if CHECKS_BY_ID[issue.check_id].classification == "human_review":
        return "needs_human_review"
    return "detected"  # auto-fixable, not repaired (repair is Phase 5)


def _where(issue: Issue) -> str:
    """Human-readable location for Location.description."""
    ref = issue.object_ref or ""
    if issue.page is not None:
        return f"Page {issue.page}"
    if ref.startswith(("Info/", "Metadata/")):
        return "Document metadata"
    if ref.startswith("Catalog/ViewerPreferences"):
        return "Document viewer preferences"
    if ref.startswith("Catalog/Lang"):
        return "Document catalog (language)"
    return "Whole document"


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
        elif issue.issue_type == "title_missing_from_xmp":
            title = str(pdf.docinfo.get("/Title", "")).strip()
            with pdf.open_metadata(set_pikepdf_as_editor=False) as meta:
                meta["dc:title"] = title
            actions[issue.issue_type] = "Copied the document title into the XMP metadata"
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
                           f"{f['location']['description']}. Status: {f['status']}."))
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


# --- Optional zip output (POST /process with output=zip) ---------------------

def results_zip_name(result: EvaluationResult) -> str:
    """Download name for the zip, e.g. "annual_report_results.zip" (safe characters only)."""
    stem = re.sub(r"[^A-Za-z0-9._-]+", "_", PurePath(result.input.file_name).stem).strip("._")
    return f"{stem or 'upload'}_results.zip"


def build_results_zip(result: EvaluationResult, original: bytes) -> bytes:
    """Zip with the uploaded PDF, the output PDF, the report PDF and result.json.

    result.json is the same EvaluationResult as the JSON response, except that
    output_pdf and report_pdf have no content_base64: those PDFs are files in the zip
    (named by their file_name).
    """
    body = result.model_dump(mode="json")
    for key in ("output_pdf", "report_pdf"):
        body[key].pop("content_base64", None)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("original.pdf", original)
        zf.writestr(result.output_pdf.file_name, base64.b64decode(result.output_pdf.content_base64))
        zf.writestr(result.report_pdf.file_name, base64.b64decode(result.report_pdf.content_base64))
        zf.writestr("result.json", json.dumps(body, indent=2, ensure_ascii=False))
    return buf.getvalue()


# --- Whole pipeline ----------------------------------------------------------

def _finding(fid: str, issue: Issue, status: FindingStatus) -> Finding:
    check = CHECKS_BY_ID[issue.check_id]
    explanation = issue.description
    if issue.suggestion:
        explanation += f" Suggested fix: {issue.suggestion.strip()}"
    return Finding(
        finding_id=fid,
        check_id=issue.check_id,
        issue_type=issue.issue_type,
        wcag_criterion=check.wcag_criterion,
        wcag_level=check.wcag_level,
        location=Location(page=issue.page, object_ref=issue.object_ref,
                          description=_where(issue)),
        evaluation_result=issue.evaluation_result,
        classification=check.classification,
        status=status,
        fix_description=explanation,
    )


def _limitations(run: CheckRun, ctx: CheckContext, repaired: bool) -> list[str]:
    notes = []
    if run.not_implemented:
        notes.append("Checks " + ", ".join(run.not_implemented)
                     + " are not implemented yet and were not performed.")
    for check_id, reason in run.failed.items():
        notes.append(f"{check_id} could not be completed ({reason}) and was not performed.")
    if "verapdf" in ctx.__dict__ and not ctx.verapdf.available:
        notes.append(f"PDF/UA-1 validation with veraPDF was not used ({ctx.verapdf.error}); "
                     "checks used pikepdf and PyMuPDF only.")
    if not repaired:
        notes.append("Automatic repair is not enabled in this version (planned for Phase 5): "
                     "auto-fixable findings are reported as detected and the PDF is "
                     "returned unchanged.")
    notes.append("Human-review findings are never repaired automatically.")
    notes.append("Automated checks cannot confirm every WCAG 2.1 requirement; a person "
                 "should review the document.")
    return notes


def _repair_and_revalidate(pdf: pikepdf.Pdf, data: bytes, file_name: str, run: CheckRun):
    """Phase 5 (ENABLE_REPAIRS): fix auto-fixable issues, then re-run the checks."""
    fixable = [i for i in run.issues if _status(i) == "detected"]
    actions = repair(pdf, fixable, file_name) if fixable else {}
    if not actions:
        return data, actions, run.issues
    out = io.BytesIO()
    pdf.save(out)
    repaired_bytes = out.getvalue()
    with pikepdf.open(io.BytesIO(repaired_bytes)) as repaired:
        after, after_ctx = evaluate(repaired_bytes, file_name, repaired)
        after_ctx.close()
    return repaired_bytes, actions, after.issues


def run_pipeline(data: bytes, file_name: str) -> EvaluationResult:
    file_name = file_name or "upload.pdf"
    pdf = validate_input(data)  # opened from an in-memory copy; `data` is never changed
    try:
        run, ctx = evaluate(data, file_name, pdf)
        try:
            if ENABLE_REPAIRS:
                output_bytes, actions, remaining = _repair_and_revalidate(pdf, data, file_name, run)
            else:
                output_bytes, actions, remaining = data, {}, run.issues
            limitations = _limitations(run, ctx, repaired=ENABLE_REPAIRS)
        finally:
            ctx.close()
    finally:
        pdf.close()

    remaining_keys = {(i.check_id, i.issue_type) for i in remaining}
    original_keys = {(i.check_id, i.issue_type) for i in run.issues}
    findings: list[Finding] = []
    repairs: list[Repair] = []
    for n, issue in enumerate(run.issues, start=1):
        fid = f"F-{n}"
        status = _status(issue)
        if issue.issue_type in actions:
            fixed = (issue.check_id, issue.issue_type) not in remaining_keys
            status = "fixed" if fixed else "repair_failed"
            repairs.append(Repair(repair_id=f"R-{len(repairs) + 1}", finding_id=fid,
                                  action=actions[issue.issue_type],
                                  validation_result="passed" if fixed else "failed"))
        findings.append(_finding(fid, issue, status))
    new_issues = [
        _finding(f"N-{n}", i, _status(i))
        for n, i in enumerate(
            (i for i in remaining if (i.check_id, i.issue_type) not in original_keys), start=1)
    ]

    human_review = [f.finding_id for f in findings if f.classification == "human_review"]
    stem = PurePath(file_name).stem
    result = {
        "evaluation_id": str(uuid.uuid4()),
        "status": "completed",
        "input": {"file_name": file_name, "sha256": _sha256(data), "size_bytes": len(data)},
        "outcome": "completed_with_repairs" if actions else "completed_no_repairs",
        "checks_performed": run.performed,
        "findings": [f.model_dump() for f in findings],
        "repairs": [r.model_dump() for r in repairs],
        "new_issues_after_repair": [f.model_dump() for f in new_issues],
        "human_review_items": human_review,
        "summary": {"total_issues": len(findings),
                    "fixed_count": sum(1 for f in findings if f.status == "fixed"),
                    "human_review_count": len(human_review)},
        "limitations": limitations,
        "compliance_statement": COMPLIANCE_STATEMENT,
    }
    report_bytes = build_report_pdf(result)
    return EvaluationResult.model_validate({
        **result,
        "output_pdf": OutputFile(file_name=f"{stem}_repaired.pdf", sha256=_sha256(output_bytes),
                                 modified=bool(actions), content_base64=_b64(output_bytes)),
        "report_pdf": OutputFile(file_name=f"{stem}_report.pdf", sha256=_sha256(report_bytes),
                                 content_base64=_b64(report_bytes)),
    })

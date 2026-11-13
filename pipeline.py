"""PDF evaluation pipeline behind POST /process.

Stages (shared spec, POST /process description):
RECEIVED -> VALIDATED -> EVALUATED -> CLASSIFIED -> REPAIRED -> REVALIDATED -> REPORTED

Input validation, then every registered check in checks/ (all eight agreed
checks; CHK-NONTEXT and CHK-STRUCTURE come from pdf_checks.py). Findings are
classified from catalog.py. Checks that are not implemented are listed in
limitations, so an empty findings list is never mistaken for "checked and passed".

Phase 5: the registered repairs in remediation/ fix what they can on a copy of
the PDF, then every check runs again on the repaired copy (re-validation). Set the
environment variable ENABLE_REPAIRS=false to switch repair off (Phase 4 behaviour:
auto-fixable findings are reported as "detected" and the PDF is returned unchanged).
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import logging
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
from checks.locate import Locator
from models import (
    ErrorCode,
    EvaluationResult,
    Finding,
    FindingStatus,
    Location,
    OutputFile,
    Repair,
)
from remediation import RepairAction, RepairContext, ai, apply_repairs, can_repair

log = logging.getLogger("pdf_accessibility.pipeline")
MAX_FILE_SIZE_BYTES = 20_971_520
COMPLIANCE_STATEMENT = "This report does not certify ADA Title II or WCAG 2.1 conformance."

# On by default (Phase 5). ENABLE_REPAIRS=false gives the Phase 4 behaviour.
ENABLE_REPAIRS = os.environ.get("ENABLE_REPAIRS", "true").lower() not in ("0", "false", "no")


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
    locator = Locator(ctx)
    for issue in run.issues:
        issue.bbox = locator.bbox(issue)
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

def repair(pdf: pikepdf.Pdf, issues: list[Issue], ctx: CheckContext,
           file_name: str) -> tuple[dict[tuple, RepairAction], RepairContext]:
    """Apply the registered repairs (remediation/) to this copy of the PDF.

    Returns Issue.key -> what was done, and the RepairContext (notes for limitations).
    """
    rctx = RepairContext(pdf=pdf, check=ctx, file_name=file_name)
    with warnings.catch_warnings(), ai.request_budget():  # LLM time/calls for this PDF
        warnings.simplefilter("ignore")  # pikepdf XMP sync warnings on odd metadata
        actions = apply_repairs([i for i in issues if can_repair(i)], rctx)
    return actions, rctx


def new_verapdf_failures(before: CheckContext, after: CheckContext) -> list[str]:
    """PDF/UA-1 rules veraPDF fails after repair but not before (if it ran both times)."""
    if "verapdf" not in before.__dict__ or "verapdf" not in after.__dict__:
        return []  # a check did not ask veraPDF, so there is nothing to compare
    old, new = before.verapdf, after.verapdf
    if not (old.available and new.available):
        return []
    known = {f.rule_id for f in old.failures}
    return sorted({f.rule_id for f in new.failures} - known)


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
    ]
    findings = result["findings"]
    if findings:
        fixed = sum(f["status"] == "fixed" for f in findings)
        failed = sum(f["status"] == "repair_failed" for f in findings)
        review = sum(f["status"] == "needs_human_review" for f in findings)
        detected = sum(f["status"] == "detected" for f in findings)
        ai_repairs = sum(r.get("method") == "llm" for r in result["repairs"])
        story += [
            p("Before and after repair", "Heading2"),
            p(f"Before repair: {len(findings)} issue(s) found."),
            p(f"After repair: {fixed} fixed and re-validated, {failed} repair(s) failed, "
              f"{detected} auto-fixable issue(s) not repaired, {review} need human review."),
            p(f"New issues after repair: {len(result['new_issues_after_repair'])}. "
              f"Repairs using AI-generated text: {ai_repairs}."),
            p("Output PDF: " + ("the repaired copy." if result["repairs"]
                                else "the original, unchanged.")),
        ]
    story.append(p("Findings", "Heading2"))
    if result["findings"]:
        for f in result["findings"]:
            story.append(p(f"{f['finding_id']} - {f['check_id']} (WCAG {f['wcag_criterion']}): "
                           f"{f['location']['description']}. "
                           f"Object: {f['location']['object_ref'] or 'none'}. "
                           f"Result: {f['evaluation_result']}. Status: {f['status']}."))
            if f.get("fix_description"):
                story.append(p(f["fix_description"]))
            if f.get("suggested_text"):
                label = (" (AI-generated, please verify)"
                         if f.get("suggestion_source") == "llm" else "")
                story.append(p(f'Suggested text{label}: "{f["suggested_text"]}"'))
    elif result["checks_performed"]:
        story.append(p("No issues found by the checks performed."))
    else:
        story.append(p("None: no checks were performed."))
    story.append(p("Automatic repairs", "Heading2"))
    if result["repairs"]:
        for r in result["repairs"]:
            ai_label = " AI-generated, please verify." if r.get("method") == "llm" else ""
            story.append(p(f"{r['repair_id']} for {r['finding_id']}: {r['action']}. "
                           f"Re-validation: {r['validation_result']}.{ai_label}"))
    else:
        story.append(p("No repairs were applied."))
    if result["new_issues_after_repair"]:
        story.append(p("New issues after repair", "Heading2"))
        for f in result["new_issues_after_repair"]:
            story.append(p(f"{f['finding_id']} - {f['check_id']}: {f['location']['description']}. "
                           f"{f.get('fix_description') or ''}"))
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

def _finding(fid: str, issue: Issue, status: FindingStatus,
             action: RepairAction | None = None) -> Finding:
    check = CHECKS_BY_ID[issue.check_id]
    suggested, source = issue.suggested_text, issue.suggestion_source
    if suggested is None and action is not None and action.applied_text:
        suggested, source = action.applied_text, action.method  # what the repair wrote
    if suggested is not None and source is None:
        source = "rule"
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
                          description=_where(issue), bbox=issue.bbox),
        evaluation_result=issue.evaluation_result,
        classification=check.classification,
        status=status,
        fix_description=explanation,
        suggested_text=suggested,
        suggestion_source=source if suggested is not None else None,
    )


def _limitations(run: CheckRun, ctx: CheckContext, repaired: bool,
                 repair_notes: list[str] | None = None, unrepaired_fixable: int = 0) -> list[str]:
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
        notes.append("Automatic repair is switched off (ENABLE_REPAIRS=false): auto-fixable "
                     "findings are reported as detected and the PDF is returned unchanged.")
    else:
        notes.append("Automatic repair covers CHK-TITLE (title, XMP title, DisplayDocTitle) "
                     "and CHK-LANG (document and passage language). Repairs are made on a "
                     "copy and re-validated by running every check again.")
        if unrepaired_fixable:
            notes.append(f"{unrepaired_fixable} auto-fixable finding(s) have no automatic "
                         "repair yet and are reported as detected.")
    notes.extend(repair_notes or [])
    notes.append("CHK-SENSORY and CHK-COLOR use English text cues; CHK-COLOR also flags "
                 "multicolor vector graphics. No OCR or raster-image color analysis is performed. "
                 "CHK-LINK inspects annotations and labels without visiting destinations. "
                 "These heuristics can miss issues and flag acceptable content; no finding "
                 "does not establish conformance. Human review of context is required.")
    notes.append("Image purpose, alternative-text accuracy, reading order, complete tagging, and "
                 "table semantics require human review. Untagged tables and vector graphics are "
                 "not inferred. A present Alt or TH tag does not establish accessibility or "
                 "semantic correctness.")
    notes.append("Human-review findings are never resolved automatically; any AI-generated "
                 "text written for them is marked and must be verified by a person.")
    notes.append("Automated checks cannot confirm every WCAG 2.1 requirement; a person "
                 "should review the document.")
    return notes


MAX_MAPPED_OBJECTS = 300_000  # bounds the object matching below on very large files
_INDIRECT_REF = re.compile(r"\b(\d+) (\d+) R\b")


def object_number_map(before: pikepdf.Pdf, after: pikepdf.Pdf) -> dict[tuple[int, int], tuple[int, int]]:
    """Map object numbers in `before` to the same objects in `after`.

    Saving a PDF renumbers its objects, so an issue at "5 0 R" before repair can be
    the same object as "6 0 R" after it. Both files are walked side by side from the
    trailer (same keys, same array positions); repairs change only small parts, so
    every object both walks reach at the same place is matched.
    """
    mapping: dict[tuple[int, int], tuple[int, int]] = {}
    stack: list[tuple[pikepdf.Object, pikepdf.Object]] = [(before.trailer, after.trailer)]
    visited: set[tuple[int, int]] = set()
    steps = 0
    while stack and steps < MAX_MAPPED_OBJECTS:
        old, new = stack.pop()
        steps += 1
        if not isinstance(old, pikepdf.Object) or not isinstance(new, pikepdf.Object):
            continue  # numbers and booleans come back as plain Python values
        if old.is_indirect:
            if old.objgen in visited:
                continue
            visited.add(old.objgen)
            if new.is_indirect:
                mapping[old.objgen] = new.objgen
        if isinstance(old, pikepdf.Array) and isinstance(new, pikepdf.Array):
            stack.extend(zip(old, new, strict=False))
        elif isinstance(old, (pikepdf.Dictionary, pikepdf.Stream)) and isinstance(
                new, (pikepdf.Dictionary, pikepdf.Stream)):
            for key in old.keys():
                if key in new and key != "/Parent":  # /Parent leads back up the tree
                    stack.append((old[key], new[key]))
    return mapping


def _translated_key(issue: Issue, mapping: dict[tuple[int, int], tuple[int, int]]) -> tuple:
    """Issue.key with object numbers rewritten to the repaired file's numbering."""
    ref = issue.object_ref
    if ref and mapping:
        def swap(m: re.Match) -> str:
            new = mapping.get((int(m[1]), int(m[2])))
            return f"{new[0]} {new[1]} R" if new else m[0]
        ref = _INDIRECT_REF.sub(swap, ref)
    return issue.check_id, issue.issue_type, issue.page, ref


def _repair_and_revalidate(pdf: pikepdf.Pdf, data: bytes, file_name: str, run: CheckRun,
                           ctx: CheckContext):
    """Phase 5: apply the registered repairs, then re-run every check on the result."""
    actions, rctx = repair(pdf, run.issues, ctx, file_name)
    if not actions:
        return data, actions, run.issues, rctx.notes, {}
    # The repaired PDF must save, reopen and pass through every check again. If any of
    # that fails, the repairs are discarded and the original PDF is returned.
    try:
        out = io.BytesIO()
        pdf.save(out)
        repaired_bytes = out.getvalue()
        with pikepdf.open(io.BytesIO(repaired_bytes)) as repaired:
            after, after_ctx = evaluate(repaired_bytes, file_name, repaired)
            try:
                new_rules = new_verapdf_failures(ctx, after_ctx)
                mapping = object_number_map(pdf, repaired)
            finally:
                after_ctx.close()
    except Exception as exc:
        log.exception("repaired PDF failed re-validation; returning the original")
        return data, {}, run.issues, rctx.notes + [
            f"Automatic repairs were discarded: the repaired PDF could not be re-validated "
            f"({type(exc).__name__}), so the original PDF is returned unchanged."], {}
    if new_rules:
        rctx.note("veraPDF reports PDF/UA-1 rules failing after repair that did not fail "
                  f"before: {', '.join(new_rules)}. Review the repaired PDF.")
    return repaired_bytes, actions, after.issues, rctx.notes, mapping


def run_pipeline(data: bytes, file_name: str) -> EvaluationResult:
    file_name = file_name or "upload.pdf"
    pdf = validate_input(data)  # opened from an in-memory copy; `data` is never changed
    try:
        run, ctx = evaluate(data, file_name, pdf)
        try:
            repair_notes: list[str] = []
            mapping: dict[tuple[int, int], tuple[int, int]] = {}
            if ENABLE_REPAIRS:
                output_bytes, actions, remaining, repair_notes, mapping = _repair_and_revalidate(
                    pdf, data, file_name, run, ctx)
            else:
                output_bytes, actions, remaining = data, {}, run.issues
            unrepaired = sum(1 for i in run.issues
                             if _status(i) == "detected" and i.key not in actions)
            limitations = _limitations(run, ctx, repaired=ENABLE_REPAIRS,
                                       repair_notes=repair_notes,
                                       unrepaired_fixable=unrepaired)
        finally:
            ctx.close()
    finally:
        pdf.close()

    # Matched by type *and* place, so one fixed and one unfixed issue of the same type
    # are told apart (Issue.key).
    # Object numbers change when the repaired PDF is saved; compare in its numbering.
    remaining_keys = {i.key for i in remaining}
    original_keys = {_translated_key(i, mapping) for i in run.issues}
    findings: list[Finding] = []
    repairs: list[Repair] = []
    for n, issue in enumerate(run.issues, start=1):
        fid = f"F-{n}"
        status = _status(issue)
        action = actions.get(issue.key)
        if action is not None:
            fixed = _translated_key(issue, mapping) not in remaining_keys
            if status == "detected":  # auto_fixable: the repair decides the status
                status = "fixed" if fixed else "repair_failed"
            # human_review stays needs_human_review: a person must verify it (spec v0.5.0)
            repairs.append(Repair(repair_id=f"R-{len(repairs) + 1}", finding_id=fid,
                                  action=action.action,
                                  validation_result="passed" if fixed else "failed",
                                  method=action.method, applied_text=action.applied_text))
        findings.append(_finding(fid, issue, status, action))
    new_issues = [
        _finding(f"N-{n}", i, _status(i))
        for n, i in enumerate(
            (i for i in remaining if i.key not in original_keys), start=1)
    ]

    human_review = [f.finding_id for f in findings + new_issues
                    if f.classification == "human_review"]
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
        "report_pdf": OutputFile(file_name=f"{stem}_AccessibilityReport.pdf",
                                 sha256=_sha256(report_bytes),
                                 content_base64=_b64(report_bytes)),
    })

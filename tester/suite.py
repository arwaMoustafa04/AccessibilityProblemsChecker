"""Team 1's planned test sequence against a target system's project API.

Each test sends real requests to the target (shared spec v0.3.0) and returns
an outcome. Tests run in order, once each, and never depend on each other.

Outcomes (course spec):
  pass  - behavior matches expectations (including the expected project error)
  fail  - the response can be evaluated and differs from expectations
  error - a system or communication problem prevents evaluation
  skip  - not executed
"""

from __future__ import annotations

import base64
import hashlib
import io
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import httpx
import pikepdf

# Tests planned for a later phase are reported as "skip" until the pod reaches it.
CURRENT_PHASE = 3

PROJECT_CALL_TIMEOUT_SECONDS = 60.0
MAX_FILE_SIZE_BYTES = 20_971_520

# Pod-defined component list and acceptance criteria (openapi.yaml, x-pod-testing).
COMPONENTS = [
    "COMP-HEALTH", "COMP-CATALOG", "COMP-VALIDATION", "COMP-DETECTION",
    "COMP-CLASSIFICATION", "COMP-REPAIR", "COMP-REVALIDATION", "COMP-REPORT",
]
ACCEPTANCE_CRITERIA = [f"AC-{n:02d}" for n in range(1, 11)]

EXPECTED_CHECKS = {
    "CHK-NONTEXT": ("1.1.1", "A", "human_review"),
    "CHK-STRUCTURE": ("1.3.1", "A", "human_review"),
    "CHK-SENSORY": ("1.3.3", "A", "human_review"),
    "CHK-COLOR": ("1.4.1", "A", "human_review"),
    "CHK-TITLE": ("2.4.2", "A", "auto_fixable"),
    "CHK-LINK": ("2.4.4", "A", "human_review"),
    "CHK-HEADINGS": ("2.4.6", "AA", "human_review"),
    "CHK-LANG": ("3.1.1", "A", "auto_fixable"),
}
EVALUATION_RESULT_FIELDS = {
    "evaluation_id", "status", "input", "outcome", "checks_performed", "findings",
    "repairs", "new_issues_after_repair", "human_review_items", "summary",
    "limitations", "compliance_statement", "output_pdf", "report_pdf",
}
COMPLIANCE_STATEMENT = "This report does not certify ADA Title II or WCAG 2.1 conformance."


class Mismatch(Exception):
    """The response was evaluated and differs from expectations -> outcome fail."""


class SystemFailure(Exception):
    """The target reported an unexpected internal failure -> error, source system."""


# --- PDF fixtures, generated in code (no files to keep in sync) ----------------

def make_pdf(title: str | None = None, lang: str | None = None,
             display_title: bool = False, user_password: str | None = None) -> bytes:
    pdf = pikepdf.new()
    pdf.add_blank_page()
    if title:
        pdf.docinfo["/Title"] = title
    if lang:
        pdf.Root.Lang = pikepdf.String(lang)
    if display_title:
        pdf.Root.ViewerPreferences = pikepdf.Dictionary(DisplayDocTitle=True)
    buf = io.BytesIO()
    if user_password is not None:
        pdf.save(buf, encryption=pikepdf.Encryption(owner="owner-pw", user=user_password))
    else:
        pdf.save(buf)
    return buf.getvalue()


def clean_pdf() -> bytes:
    return make_pdf(title="Quarterly Budget", lang="en-US", display_title=True)


def pdf_of_exact_size(size: int) -> bytes:
    """A valid, clean PDF padded with a trailing comment to exactly `size` bytes."""
    base = clean_pdf()
    padding = size - len(base) - 2
    return base + b"\n%" + b"0" * padding


# --- Helpers -------------------------------------------------------------------

@dataclass
class Context:
    client: httpx.Client
    target_url: str
    session_id: str

    def url(self, path: str) -> str:
        return self.target_url.rstrip("/") + path

    def get(self, path: str) -> httpx.Response:
        return self.client.get(self.url(path), timeout=PROJECT_CALL_TIMEOUT_SECONDS)

    def process(self, data: bytes | None, name: str = "test.pdf",
                content_type: str = "application/pdf") -> httpx.Response:
        files = {"file": (name, data, content_type)} if data is not None else None
        return self.client.post(self.url("/process"), files=files,
                                data={"session_id": self.session_id},
                                timeout=PROJECT_CALL_TIMEOUT_SECONDS)


def json_body(resp: httpx.Response) -> dict:
    try:
        return resp.json()
    except ValueError:
        raise Mismatch(f"Expected a JSON body; received {resp.text[:120]!r}.") from None


def expect_status(resp: httpx.Response, expected: int) -> None:
    if resp.status_code == expected:
        return
    if resp.status_code >= 500 and expected < 500:
        raise SystemFailure(f"Expected HTTP {expected}; the target reported an internal "
                            f"failure (HTTP {resp.status_code}): {resp.text[:200]}")
    raise Mismatch(f"Expected HTTP {expected}; received HTTP {resp.status_code}: "
                   f"{resp.text[:200]}")


def expect_error(resp: httpx.Response, status: int, codes: set[str]) -> str:
    expect_status(resp, status)
    body = json_body(resp)
    if body.get("status") != "error" or body.get("error_code") not in codes or not body.get("message"):
        raise Mismatch(f"Expected HTTP {status} with error_code in {sorted(codes)}; "
                       f"received {body}.")
    return f"Expected HTTP {status} {'/'.join(sorted(codes))}; received HTTP {status} {body['error_code']}."


def expect_evaluation(resp: httpx.Response, sent: bytes) -> dict:
    expect_status(resp, 200)
    body = json_body(resp)
    missing = EVALUATION_RESULT_FIELDS - set(body)
    if missing:
        raise Mismatch(f"EvaluationResult is missing required fields: {sorted(missing)}.")
    if body["status"] != "completed":
        raise Mismatch(f'Expected status "completed"; received {body["status"]!r}.')
    sent_hash = hashlib.sha256(sent).hexdigest()
    if body["input"].get("sha256") != sent_hash or body["input"].get("size_bytes") != len(sent):
        raise Mismatch("input.sha256/size_bytes do not describe the PDF that was sent "
                       f"(expected {sent_hash[:12]}..., {len(sent)} bytes; received "
                       f"{str(body['input'].get('sha256'))[:12]}..., {body['input'].get('size_bytes')}).")
    return body


def decode_pdf(output_file: dict, label: str) -> bytes:
    try:
        data = base64.b64decode(output_file["content_base64"], validate=True)
    except Exception:
        raise Mismatch(f"{label}.content_base64 is not valid Base64.") from None
    if not data.startswith(b"%PDF-"):
        raise Mismatch(f"{label} does not decode to a PDF.")
    if hashlib.sha256(data).hexdigest() != output_file.get("sha256"):
        raise Mismatch(f"{label}.sha256 does not match its content.")
    return data


# --- Test cases ------------------------------------------------------------------

def t_health(ctx: Context) -> str:
    resp = ctx.get("/health")
    expect_status(resp, 200)
    body = json_body(resp)
    if body.get("status") != "ok" or not isinstance(body.get("spec_version"), str):
        raise Mismatch(f'Expected {{"status": "ok", "spec_version": "<string>"}}; received {body}.')
    return f'Expected status "ok"; received status "ok", spec_version {body["spec_version"]}.'


def t_checks(ctx: Context) -> str:
    resp = ctx.get("/checks")
    expect_status(resp, 200)
    body = json_body(resp)
    checks = body.get("checks") if isinstance(body, dict) else None
    if not isinstance(checks, list):
        raise Mismatch(f'Expected {{"checks": [...]}}; received {str(body)[:200]}.')
    got = {c.get("check_id"): (c.get("wcag_criterion"), c.get("wcag_level"),
                               c.get("classification")) for c in checks}
    if len(checks) != 8 or got != EXPECTED_CHECKS:
        diffs = sorted(k for k in set(got) | set(EXPECTED_CHECKS) if got.get(k) != EXPECTED_CHECKS.get(k))
        raise Mismatch(f"Expected the 8 agreed checks; these differ: {diffs}.")
    return "Expected the 8 agreed checks and classifications; received all 8, matching."


def t_clean_pdf(ctx: Context) -> str:
    sent = clean_pdf()
    body = expect_evaluation(ctx.process(sent), sent)
    auto = [f for f in body["findings"] if f.get("check_id") in ("CHK-TITLE", "CHK-LANG")]
    if auto:
        raise Mismatch(f"Expected no CHK-TITLE/CHK-LANG findings for a PDF with a title, "
                       f"language and DisplayDocTitle; received {[f.get('issue_type') for f in auto]}.")
    if body["outcome"] != "completed_no_repairs" or body["repairs"]:
        raise Mismatch(f'Expected outcome "completed_no_repairs" and no repairs; received '
                       f'{body["outcome"]!r} with {len(body["repairs"])} repairs.')
    decode_pdf(body["report_pdf"], "report_pdf")
    if decode_pdf(body["output_pdf"], "output_pdf") != sent and body["output_pdf"].get("modified"):
        raise Mismatch("Expected the output PDF to be unchanged when no repairs apply.")
    return "Expected 200 with no repairs; received completed_no_repairs, both PDFs returned."


def t_repair_title_and_lang(ctx: Context) -> str:
    sent = make_pdf()  # no title, no language
    original_hash = hashlib.sha256(sent).hexdigest()
    body = expect_evaluation(ctx.process(sent, name="missing_title_and_lang.pdf"), sent)
    findings = body["findings"]
    for check_id in ("CHK-TITLE", "CHK-LANG"):
        mine = [f for f in findings if f.get("check_id") == check_id]
        if not mine:
            raise Mismatch(f"Expected a {check_id} finding for a PDF without it; received none.")
        for f in mine:
            if f.get("classification") != "auto_fixable" or f.get("status") != "fixed":
                raise Mismatch(f"Expected {check_id} finding to be auto_fixable and fixed; "
                               f"received {f.get('classification')}/{f.get('status')}.")
    by_finding = {r.get("finding_id"): r for r in body["repairs"]}
    for f in findings:
        if f.get("check_id") in ("CHK-TITLE", "CHK-LANG"):
            r = by_finding.get(f.get("finding_id"))
            if not r or r.get("validation_result") != "passed":
                raise Mismatch(f"Expected a repair with validation_result passed for "
                               f"{f.get('finding_id')}; received {r}.")
    if body["outcome"] != "completed_with_repairs":
        raise Mismatch(f'Expected outcome "completed_with_repairs"; received {body["outcome"]!r}.')
    repaired = decode_pdf(body["output_pdf"], "output_pdf")
    with pikepdf.open(io.BytesIO(repaired)) as pdf:
        if not str(pdf.Root.get("/Lang", "")).strip():
            raise Mismatch("Repaired PDF still has no document language.")
        if not str(pdf.docinfo.get("/Title", "")).strip():
            with pdf.open_metadata(set_pikepdf_as_editor=False) as meta:
                if not str(meta.get("dc:title", "") or "").strip():
                    raise Mismatch("Repaired PDF still has no title.")
    if hashlib.sha256(sent).hexdigest() != original_hash:
        raise Mismatch("The uploaded copy changed during the request.")
    return ("Expected CHK-TITLE and CHK-LANG found, fixed and re-validated; received all "
            "fixed with validation passed and a repaired PDF.")


def t_no_compliance_claim(ctx: Context) -> str:
    sent = clean_pdf()
    body = expect_evaluation(ctx.process(sent), sent)
    if body["compliance_statement"] != COMPLIANCE_STATEMENT:
        raise Mismatch(f"Expected the fixed compliance_statement; received {body['compliance_statement']!r}.")
    text = " ".join(str(x) for x in body["limitations"]).lower()
    if "ada compliant" in text or "fully compliant" in text:
        raise Mismatch("limitations claim the PDF is compliant.")
    return "Expected no compliance claim; received the fixed non-certification statement."


def t_non_pdf(ctx: Context) -> str:
    return expect_error(ctx.process(b"PK\x03\x04 not a pdf", name="document.docx",
                                    content_type="application/octet-stream"),
                        415, {"INVALID_FILE_TYPE"})


def t_missing_file(ctx: Context) -> str:
    return expect_error(ctx.process(None), 400, {"MISSING_FILE"})


def t_corrupted(ctx: Context) -> str:
    return expect_error(ctx.process(b"%PDF-1.7\n1 0 obj << /Broken"),
                        422, {"CORRUPTED_PDF", "UNREADABLE_PDF"})


def t_password_protected(ctx: Context) -> str:
    return expect_error(ctx.process(make_pdf(user_password="secret")),
                        422, {"PASSWORD_PROTECTED_PDF", "ENCRYPTED_PDF"})


def t_over_limit(ctx: Context) -> str:
    return expect_error(ctx.process(pdf_of_exact_size(MAX_FILE_SIZE_BYTES + 1)),
                        413, {"FILE_TOO_LARGE"})


def t_at_limit(ctx: Context) -> str:
    sent = pdf_of_exact_size(MAX_FILE_SIZE_BYTES)
    expect_evaluation(ctx.process(sent), sent)
    return "Expected a valid PDF of exactly 20,971,520 bytes to be accepted; received 200."


# --- Shared test set: real files made by the team (tester/fixtures/README.md) ---

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def fixture(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


# Issues the team built into accessibilityIssues.pdf, by agreed check (fixtures/README.md).
# Contrast (WCAG 1.4.3) is also present but is not one of the eight agreed checks.
ISSUES_PDF_EXPECTED = {
    "CHK-STRUCTURE": "human_review",  # no tags/structure tree; table without header cells
    "CHK-LANG": "auto_fixable",       # no document language
    "CHK-TITLE": "auto_fixable",      # empty document title
    "CHK-NONTEXT": "human_review",    # image without alt text
    "CHK-LINK": "human_review",       # "Click here" link
}


def t_fixture_good(ctx: Context) -> str:
    sent = fixture("goodAccessible.pdf")
    body = expect_evaluation(ctx.process(sent, name="goodAccessible.pdf"), sent)
    auto = [f.get("issue_type") for f in body["findings"]
            if f.get("check_id") in ("CHK-TITLE", "CHK-LANG")]
    if auto:
        raise Mismatch("goodAccessible.pdf has a title, language and DisplayDocTitle; expected no "
                       f"CHK-TITLE/CHK-LANG findings, received {auto}.")
    if body["repairs"]:
        raise Mismatch(f"Expected no repairs for goodAccessible.pdf; received {len(body['repairs'])}.")
    decode_pdf(body["report_pdf"], "report_pdf")
    return "Expected goodAccessible.pdf accepted (200) with no repairs; received that."


def t_fixture_issues_accepted(ctx: Context) -> str:
    sent = fixture("accessibilityIssues.pdf")
    body = expect_evaluation(ctx.process(sent, name="accessibilityIssues.pdf"), sent)
    decode_pdf(body["output_pdf"], "output_pdf")
    decode_pdf(body["report_pdf"], "report_pdf")
    return ("Expected accessibilityIssues.pdf accepted (200) with a contract-conforming result; "
            "received that.")


def t_fixture_non_pdf(ctx: Context) -> str:
    return expect_error(ctx.process(fixture("NonPDF.docx"), name="NonPDF.docx",
                                    content_type="application/octet-stream"),
                        415, {"INVALID_FILE_TYPE"})


def t_fixture_encrypted(ctx: Context) -> str:
    return expect_error(ctx.process(fixture("encrypted.pdf"), name="encrypted.pdf"),
                        422, {"ENCRYPTED_PDF"})


def t_fixture_password(ctx: Context) -> str:
    return expect_error(ctx.process(fixture("passwordProtected.pdf"), name="passwordProtected.pdf"),
                        422, {"PASSWORD_PROTECTED_PDF"})


def t_fixture_issues_detected(ctx: Context) -> str:
    sent = fixture("accessibilityIssues.pdf")
    body = expect_evaluation(ctx.process(sent, name="accessibilityIssues.pdf"), sent)
    missing_checks = sorted(set(EXPECTED_CHECKS) - set(body["checks_performed"]))
    if missing_checks:
        raise Mismatch(f"Expected all 8 checks performed; missing {missing_checks}.")
    found = {f.get("check_id"): f for f in body["findings"]}
    for check_id, classification in ISSUES_PDF_EXPECTED.items():
        f = found.get(check_id)
        if f is None:
            raise Mismatch(f"Expected a {check_id} finding in accessibilityIssues.pdf; received none.")
        if f.get("classification") != classification:
            raise Mismatch(f"Expected {check_id} classified {classification}; "
                           f"received {f.get('classification')}.")
        if classification == "human_review" and f.get("status") != "needs_human_review":
            raise Mismatch(f"Expected {check_id} to stay needs_human_review; received {f.get('status')}.")
    return ("Expected the 5 built-in issue types found and correctly classified; human-review "
            "issues left unresolved; received that.")


def t_fixture_issues_repaired(ctx: Context) -> str:
    sent = fixture("accessibilityIssues.pdf")
    body = expect_evaluation(ctx.process(sent, name="accessibilityIssues.pdf"), sent)
    for check_id in ("CHK-TITLE", "CHK-LANG"):
        mine = [f for f in body["findings"] if f.get("check_id") == check_id]
        if not mine or any(f.get("status") != "fixed" for f in mine):
            raise Mismatch(f"Expected {check_id} found and fixed in accessibilityIssues.pdf; "
                           f"received {[f.get('status') for f in mine]}.")
    repaired = decode_pdf(body["output_pdf"], "output_pdf")
    with pikepdf.open(io.BytesIO(repaired)) as pdf:
        if not str(pdf.Root.get("/Lang", "")).strip():
            raise Mismatch("Repaired accessibilityIssues.pdf still has no document language.")
    return "Expected title and language fixed in accessibilityIssues.pdf; received that."


@dataclass(frozen=True)
class TestCase:
    test_id: str
    run: Callable[[Context], str]
    components: tuple[str, ...] = field(default=())
    criteria: tuple[str, ...] = field(default=())
    phase: int = 3  # first phase in which this test is expected to run


SUITE: list[TestCase] = [
    TestCase("T-01", t_health, ("COMP-HEALTH",)),
    TestCase("T-02", t_checks, ("COMP-CATALOG",)),
    TestCase("T-03", t_clean_pdf, ("COMP-REPORT",), ("AC-01", "AC-08")),
    TestCase("T-04", t_repair_title_and_lang,
             ("COMP-DETECTION", "COMP-CLASSIFICATION", "COMP-REPAIR",
              "COMP-REVALIDATION", "COMP-REPORT"),
             ("AC-03", "AC-04", "AC-05", "AC-06", "AC-08"), phase=5),
    TestCase("T-05", t_no_compliance_claim, ("COMP-REPORT",), ("AC-09",)),
    TestCase("T-06", t_non_pdf, ("COMP-VALIDATION",), ("AC-02",)),
    TestCase("T-07", t_missing_file, ("COMP-VALIDATION",), ("AC-02",)),
    TestCase("T-08", t_corrupted, ("COMP-VALIDATION",), ("AC-02",)),
    TestCase("T-09", t_password_protected, ("COMP-VALIDATION",), ("AC-02",)),
    TestCase("T-10", t_over_limit, ("COMP-VALIDATION",), ("AC-10",)),
    TestCase("T-11", t_at_limit, ("COMP-VALIDATION",), ("AC-10",)),
    # Shared test set (team-made files in tester/fixtures/)
    TestCase("T-12", t_fixture_good, ("COMP-REPORT",), ("AC-01", "AC-08")),
    TestCase("T-13", t_fixture_issues_accepted, ("COMP-REPORT",), ("AC-01",)),
    TestCase("T-14", t_fixture_non_pdf, ("COMP-VALIDATION",), ("AC-02",)),
    TestCase("T-15", t_fixture_encrypted, ("COMP-VALIDATION",), ("AC-02",)),
    TestCase("T-16", t_fixture_password, ("COMP-VALIDATION",), ("AC-02",)),
    TestCase("T-17", t_fixture_issues_detected, ("COMP-DETECTION", "COMP-CLASSIFICATION"),
             ("AC-03", "AC-04", "AC-07"), phase=4),
    TestCase("T-18", t_fixture_issues_repaired,
             ("COMP-REPAIR", "COMP-REVALIDATION"), ("AC-05", "AC-06"), phase=5),
]

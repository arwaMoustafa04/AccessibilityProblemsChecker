import base64
import hashlib
import io
import uuid

import pikepdf
import pytest
from fastapi.testclient import TestClient

from main import SPEC_VERSION, app

client = TestClient(app)

EXPECTED_CHECKS = {
    "CHK-NONTEXT": ("Non-text Content", "1.1.1", "A", "human_review"),
    "CHK-STRUCTURE": ("Info and Relationships", "1.3.1", "A", "human_review"),
    "CHK-SENSORY": ("Sensory Characteristics", "1.3.3", "A", "human_review"),
    "CHK-COLOR": ("Use of Color", "1.4.1", "A", "human_review"),
    "CHK-TITLE": ("Page Titled", "2.4.2", "A", "auto_fixable"),
    "CHK-LINK": ("Link Purpose (In Context)", "2.4.4", "A", "human_review"),
    "CHK-HEADINGS": ("Headings and Labels", "2.4.6", "AA", "human_review"),
    "CHK-LANG": ("Language of Page", "3.1.1", "A", "auto_fixable"),
}


# --- PDF fixtures, generated in code -----------------------------------------

def make_pdf(title: str | None = None, lang: str | None = None,
             display_title: bool = False, encrypt: bool = False,
             user_password: str = "") -> bytes:
    pdf = pikepdf.new()
    pdf.add_blank_page()
    if title:
        pdf.docinfo["/Title"] = title
    if lang:
        pdf.Root.Lang = pikepdf.String(lang)
    if display_title:
        pdf.Root.ViewerPreferences = pikepdf.Dictionary(DisplayDocTitle=True)
    buf = io.BytesIO()
    if encrypt:
        pdf.save(buf, encryption=pikepdf.Encryption(owner="owner", user=user_password))
    else:
        pdf.save(buf)
    return buf.getvalue()


def post_pdf(data: bytes, name: str = "doc.pdf", **form):
    return client.post("/process", files={"file": (name, data, "application/pdf")},
                       data=form)


# --- GET /health and GET /checks ---------------------------------------------

def test_health_returns_expected_contract() -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/json"
    assert response.json() == {"status": "ok", "spec_version": SPEC_VERSION}


def test_checks_returns_agreed_catalog() -> None:
    response = client.get("/checks")
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"checks"}
    checks = body["checks"]
    assert len(checks) == 8
    assert {c["check_id"] for c in checks} == set(EXPECTED_CHECKS)
    for c in checks:
        assert set(c) == {"check_id", "name", "wcag_criterion", "wcag_level",
                          "classification"}
        assert (c["name"], c["wcag_criterion"], c["wcag_level"],
                c["classification"]) == EXPECTED_CHECKS[c["check_id"]]


@pytest.mark.parametrize("path", ["/health", "/checks"])
def test_endpoint_methods_are_read_only(path: str) -> None:
    assert client.post(path).status_code == 405


# --- POST /process: errors ----------------------------------------------------

def test_missing_file_is_400() -> None:
    response = client.post("/process", data={})
    assert response.status_code == 400
    assert response.json()["error_code"] == "MISSING_FILE"


def test_non_pdf_is_415() -> None:
    response = post_pdf(b"PK\x03\x04 this is a docx", name="doc.docx")
    assert response.status_code == 415
    assert response.json() == {"status": "error", "error_code": "INVALID_FILE_TYPE",
                               "message": "Input must be a PDF file."}


def test_too_large_is_413() -> None:
    data = b"%PDF-1.7\n" + b"0" * (20_971_520 - 8)
    assert len(data) == 20_971_521
    response = post_pdf(data)
    assert response.status_code == 413
    assert response.json()["error_code"] == "FILE_TOO_LARGE"


def test_corrupted_pdf_is_422() -> None:
    response = post_pdf(b"%PDF-1.7\nthis is not really a pdf")
    assert response.status_code == 422
    assert response.json()["error_code"] == "CORRUPTED_PDF"


def test_password_protected_pdf_is_422() -> None:
    response = post_pdf(make_pdf(encrypt=True, user_password="secret"))
    assert response.status_code == 422
    assert response.json()["error_code"] == "PASSWORD_PROTECTED_PDF"


def test_encrypted_pdf_is_422() -> None:
    response = post_pdf(make_pdf(encrypt=True))
    assert response.status_code == 422
    assert response.json()["error_code"] == "ENCRYPTED_PDF"


# --- POST /process: success ---------------------------------------------------

def test_phase3_valid_pdf_runs_no_checks_and_is_unchanged() -> None:
    """Phase 3 (default): valid PDFs get a well-formed result with no checks or repairs."""
    original = make_pdf()  # missing title and language, but nothing should be fixed yet
    response = post_pdf(original, name="annual_report.pdf")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "completed"
    assert body["outcome"] == "completed_no_repairs"
    assert body["checks_performed"] == []
    assert body["findings"] == [] and body["repairs"] == []
    assert body["summary"] == {"total_issues": 0, "fixed_count": 0, "human_review_count": 0}
    assert "Phase 4" in body["limitations"][0]
    assert body["output_pdf"]["modified"] is False
    assert base64.b64decode(body["output_pdf"]["content_base64"]) == original
    assert base64.b64decode(body["report_pdf"]["content_base64"]).startswith(b"%PDF-")


@pytest.fixture
def title_lang_on(monkeypatch):
    """Turn on the early Phase 4-5 work (off by default in Phase 3)."""
    import pipeline
    monkeypatch.setattr(pipeline, "ENABLE_TITLE_LANG_CHECKS", True)


def test_pdf_missing_title_and_language_is_repaired(title_lang_on) -> None:
    original = make_pdf()
    original_hash = hashlib.sha256(original).hexdigest()
    response = post_pdf(original, name="annual_report.pdf")
    assert response.status_code == 200
    body = response.json()

    assert body["status"] == "completed"
    assert body["outcome"] == "completed_with_repairs"
    assert body["input"] == {"file_name": "annual_report.pdf", "sha256": original_hash,
                             "size_bytes": len(original)}
    assert body["checks_performed"] == ["CHK-TITLE", "CHK-LANG"]
    assert {f["issue_type"] for f in body["findings"]} == {
        "missing_document_title", "display_doc_title_not_set", "missing_document_language"}
    assert all(f["status"] == "fixed" for f in body["findings"])
    assert all(r["validation_result"] == "passed" for r in body["repairs"])
    assert body["new_issues_after_repair"] == []
    assert body["summary"] == {"total_issues": 3, "fixed_count": 3, "human_review_count": 0}
    assert body["compliance_statement"] == (
        "This report does not certify ADA Title II or WCAG 2.1 conformance.")

    repaired = base64.b64decode(body["output_pdf"]["content_base64"])
    assert body["output_pdf"]["modified"] is True
    assert hashlib.sha256(repaired).hexdigest() == body["output_pdf"]["sha256"]
    with pikepdf.open(io.BytesIO(repaired)) as pdf:
        assert str(pdf.docinfo["/Title"]) == "annual report"
        assert str(pdf.Root.Lang) == "en-US"
        assert pdf.Root.ViewerPreferences.DisplayDocTitle is True

    report = base64.b64decode(body["report_pdf"]["content_base64"])
    assert report.startswith(b"%PDF-")
    # The upload itself was never modified (REQ-07, REQ-17).
    assert hashlib.sha256(original).hexdigest() == original_hash


def test_clean_pdf_is_returned_unchanged(title_lang_on) -> None:
    original = make_pdf(title="Budget", lang="en-US", display_title=True)
    body = post_pdf(original).json()
    assert body["outcome"] == "completed_no_repairs"
    assert body["findings"] == [] and body["repairs"] == []
    assert body["output_pdf"]["modified"] is False
    assert base64.b64decode(body["output_pdf"]["content_base64"]) == original


# --- Course test endpoints ----------------------------------------------------

def test_setup_then_report_coverage() -> None:
    sid = str(uuid.uuid4())
    response = client.post("/test/setup", json={"session_id": sid, "setup": {}})
    assert response.status_code == 201
    assert response.json() == {"session_id": sid}

    before = client.get("/test/report", params={"session_id": sid}).json()
    assert before["session_id"] == sid
    assert before["coverage"]["code"]["covered"] == 0

    assert post_pdf(make_pdf(), session_id=sid).status_code == 200
    after = client.get("/test/report", params={"session_id": sid}).json()["coverage"]["code"]
    assert 0 < after["covered"] <= after["total"]
    assert after["basis"]

    # Reading the report does not change it.
    again = client.get("/test/report", params={"session_id": sid}).json()["coverage"]["code"]
    assert again == after


def test_setup_duplicate_session_is_409() -> None:
    sid = str(uuid.uuid4())
    assert client.post("/test/setup", json={"session_id": sid}).status_code == 201
    response = client.post("/test/setup", json={"session_id": sid, "setup": {}})
    assert response.status_code == 409
    assert response.json()["source"] == "system" and response.json()["message"]


@pytest.mark.parametrize("body", [{}, {"session_id": ""}, {"setup": {}}])
def test_setup_invalid_request_is_400(body: dict) -> None:
    response = client.post("/test/setup", json=body)
    assert response.status_code == 400
    assert response.json()["source"] == "system"


def test_report_unknown_session_is_404() -> None:
    response = client.get("/test/report", params={"session_id": "never-created"})
    assert response.status_code == 404
    assert response.json()["source"] == "system"


def test_report_without_session_id_is_400() -> None:
    assert client.get("/test/report").status_code == 400

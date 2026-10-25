"""Unit tests for the Phase 4 checks (CHK-TITLE, CHK-LANG, CHK-HEADINGS), the
check registry, and the veraPDF integration. Test PDFs are generated in code."""

import io
import stat
import textwrap
from pathlib import Path

import pikepdf
import pytest

import checks
from checks import CheckContext, run_checks
from checks import headings as headings_check
from checks import lang as lang_check
from checks import title as title_check
from checks.verapdf import parse_mrr, run_verapdf

FIXTURES = Path(__file__).parent / "tester" / "fixtures"


# --- PDF builders -------------------------------------------------------------

def _save(pdf: pikepdf.Pdf) -> bytes:
    buf = io.BytesIO()
    pdf.save(buf)
    return buf.getvalue()


def _set_title(pdf: pikepdf.Pdf, title: str, xmp: bool = True) -> None:
    pdf.docinfo["/Title"] = title
    if xmp:
        with pdf.open_metadata(set_pikepdf_as_editor=False) as meta:
            meta["dc:title"] = title


def clean_pdf(title: str = "Annual Budget 2026", lang: str = "en-US") -> bytes:
    """Title in Info and XMP, DisplayDocTitle, language: no title/lang/heading issues."""
    pdf = pikepdf.new()
    pdf.add_blank_page()
    _set_title(pdf, title)
    pdf.Root.ViewerPreferences = pikepdf.Dictionary(DisplayDocTitle=True)
    pdf.Root.Lang = pikepdf.String(lang)
    return _save(pdf)


def tagged_pdf(tags: list[str], empty: tuple[int, ...] = (), role_map: dict | None = None,
               elem_lang: str | None = None) -> bytes:
    """A clean, tagged PDF whose structure tree holds one element per tag, in order."""
    pdf = pikepdf.open(io.BytesIO(clean_pdf()))
    page = pdf.pages[0].obj
    doc_elem = pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.StructElem,
                                                    S=pikepdf.Name.Document))
    kids = []
    for n, tag in enumerate(tags):
        elem = pikepdf.Dictionary(Type=pikepdf.Name.StructElem, S=pikepdf.Name(tag),
                                  P=doc_elem, Pg=page)
        if n not in empty:
            elem.K = n  # an MCID: this element has marked content
        if elem_lang is not None:
            elem.Lang = pikepdf.String(elem_lang)
        kids.append(pdf.make_indirect(elem))
    doc_elem.K = pikepdf.Array(kids)
    tree = pikepdf.Dictionary(Type=pikepdf.Name.StructTreeRoot, K=doc_elem)
    if role_map:
        tree.RoleMap = pikepdf.Dictionary({k: pikepdf.Name(v) for k, v in role_map.items()})
    pdf.Root.StructTreeRoot = pdf.make_indirect(tree)
    pdf.Root.MarkInfo = pikepdf.Dictionary(Marked=True)
    return _save(pdf)


def text_pdf(heading: str = "Campus Library Services") -> bytes:
    """Untagged PDF with one large heading line above body text (made with reportlab)."""
    from reportlab.pdfgen import canvas
    buf = io.BytesIO()
    c = canvas.Canvas(buf)
    c.setFont("Helvetica-Bold", 20)
    c.drawString(72, 750, heading)
    c.setFont("Helvetica", 11)
    for n in range(12):
        c.drawString(72, 720 - n * 14, f"This is body text line {n} of the document explaining services.")
    c.save()
    pdf = pikepdf.open(io.BytesIO(buf.getvalue()))
    _set_title(pdf, "Library Guide")
    pdf.Root.ViewerPreferences = pikepdf.Dictionary(DisplayDocTitle=True)
    pdf.Root.Lang = pikepdf.String("en-US")
    return _save(pdf)


def form_pdf(label: str | None) -> bytes:
    pdf = pikepdf.open(io.BytesIO(clean_pdf()))
    field = pikepdf.Dictionary(FT=pikepdf.Name.Tx, T=pikepdf.String("email"),
                               Subtype=pikepdf.Name.Widget, P=pdf.pages[0].obj,
                               Rect=[72, 700, 300, 720])
    if label:
        field.TU = pikepdf.String(label)
    field = pdf.make_indirect(field)
    pdf.Root.AcroForm = pikepdf.Dictionary(Fields=[field])
    return _save(pdf)


def issues_of(fn, data: bytes, file_name: str = "doc.pdf"):
    with pikepdf.open(io.BytesIO(data)) as pdf:
        ctx = CheckContext(data, file_name, pdf)
        try:
            return fn(ctx)
        finally:
            ctx.close()


def types(found) -> set[str]:
    return {i.issue_type for i in found}


@pytest.fixture(autouse=True)
def no_verapdf(monkeypatch):
    """Tests run without veraPDF unless a test installs the fake one."""
    monkeypatch.setenv("VERAPDF_PATH", "")
    monkeypatch.setattr("checks.verapdf.shutil.which", lambda name: None)


# --- CHK-TITLE ----------------------------------------------------------------

def test_title_clean_pdf_passes() -> None:
    assert issues_of(title_check.check, clean_pdf()) == []


def test_title_missing() -> None:
    pdf = pikepdf.new()
    pdf.add_blank_page()
    found = issues_of(title_check.check, _save(pdf))
    assert types(found) == {"missing_document_title", "display_doc_title_not_set"}
    assert all(i.evaluation_result == "fail" and i.check_id == "CHK-TITLE" for i in found)


def test_title_only_in_info_dictionary() -> None:
    pdf = pikepdf.new()
    pdf.add_blank_page()
    _set_title(pdf, "Annual Budget", xmp=False)
    pdf.Root.ViewerPreferences = pikepdf.Dictionary(DisplayDocTitle=True)
    assert types(issues_of(title_check.check, _save(pdf))) == {"title_missing_from_xmp"}


@pytest.mark.parametrize("title", ["Untitled", "Microsoft Word - budget.docx", "scan_0042.pdf",
                                   "budget_final"])
def test_title_placeholder_needs_review(title) -> None:
    found = issues_of(title_check.check, clean_pdf(title=title), file_name="budget_final.pdf")
    assert types(found) == {"title_not_descriptive"}
    assert found[0].evaluation_result == "needs_review"


def test_good_accessible_fixture_has_no_title_lang_heading_issues() -> None:
    data = (FIXTURES / "goodAccessible.pdf").read_bytes()
    for fn in (title_check.check, lang_check.check, headings_check.check):
        assert issues_of(fn, data, "goodAccessible.pdf") == []


def test_issues_fixture_has_expected_title_and_lang_issues() -> None:
    data = (FIXTURES / "accessibilityIssues.pdf").read_bytes()
    assert "missing_document_title" in types(issues_of(title_check.check, data))
    assert types(issues_of(lang_check.check, data)) == {"missing_document_language"}


# --- CHK-LANG -----------------------------------------------------------------

@pytest.mark.parametrize("tag", ["en", "en-US", "es-MX", "zh-Hant-TW", "ar"])
def test_lang_valid(tag) -> None:
    assert issues_of(lang_check.check, clean_pdf(lang=tag)) == []


@pytest.mark.parametrize("tag", ["english", "und", "12", "en_US"])
def test_lang_invalid(tag) -> None:
    assert types(issues_of(lang_check.check, clean_pdf(lang=tag))) == {"invalid_document_language"}


def test_lang_missing() -> None:
    pdf = pikepdf.open(io.BytesIO(clean_pdf()))
    del pdf.Root.Lang
    found = issues_of(lang_check.check, _save(pdf))
    assert types(found) == {"missing_document_language"}
    assert found[0].object_ref == "Catalog/Lang"


def test_lang_invalid_on_structure_element() -> None:
    found = issues_of(lang_check.check, tagged_pdf(["/P"], elem_lang="xx_bad"))
    assert types(found) == {"invalid_element_language"}
    assert found[0].page == 1


# --- CHK-HEADINGS -------------------------------------------------------------

def test_headings_in_order_pass() -> None:
    assert issues_of(headings_check.check, tagged_pdf(["/H1", "/P", "/H2", "/H3", "/H2"])) == []


def test_heading_level_skipped() -> None:
    found = issues_of(headings_check.check, tagged_pdf(["/H1", "/H3"]))
    assert types(found) == {"heading_level_skipped"}
    assert found[0].page == 1 and "H1 to H3" in found[0].description


def test_first_heading_not_h1() -> None:
    assert types(issues_of(headings_check.check, tagged_pdf(["/H2", "/H3"]))) == {"first_heading_not_h1"}


def test_mixed_and_empty_headings() -> None:
    found = issues_of(headings_check.check, tagged_pdf(["/H1", "/H", "/H2"], empty=(2,)))
    assert types(found) == {"mixed_heading_tags", "empty_heading"}


def test_heading_role_map_is_followed() -> None:
    found = issues_of(headings_check.check, tagged_pdf(
        ["/Title1", "/Sub3"], role_map={"/Title1": "/H1", "/Sub3": "/H3"}))
    assert types(found) == {"heading_level_skipped"}


def test_visual_heading_without_tags_needs_review() -> None:
    found = issues_of(headings_check.check, text_pdf())
    assert types(found) == {"headings_not_tagged"}
    assert found[0].evaluation_result == "needs_review" and found[0].page == 1
    assert "Campus Library Services" in found[0].description


def test_form_field_label() -> None:
    assert types(issues_of(headings_check.check, form_pdf(None))) == {"form_field_without_label"}
    assert issues_of(headings_check.check, form_pdf("Email address")) == []


# --- Registry -----------------------------------------------------------------

def test_registry_runs_in_catalog_order_and_reports_missing_checks() -> None:
    data = clean_pdf()
    with pikepdf.open(io.BytesIO(data)) as pdf:
        run = run_checks(CheckContext(data, "a.pdf", pdf))
    assert run.performed == ["CHK-TITLE", "CHK-HEADINGS", "CHK-LANG"]
    assert set(run.not_implemented) == {"CHK-NONTEXT", "CHK-STRUCTURE", "CHK-SENSORY",
                                        "CHK-COLOR", "CHK-LINK"}


def test_registry_rejects_issue_for_another_check() -> None:
    def wrong(ctx):
        return [checks.Issue("CHK-LANG", "x", "y")]
    data = clean_pdf()
    with pikepdf.open(io.BytesIO(data)) as pdf:
        run = run_checks(CheckContext(data, "a.pdf", pdf), {"CHK-TITLE": wrong})
    assert run.performed == [] and "CHK-TITLE" in run.failed


# --- veraPDF ------------------------------------------------------------------

MRR = textwrap.dedent("""\
    <?xml version="1.0" encoding="utf-8"?>
    <report>
      <jobs><job>
        <item size="1000"><name>/tmp/x.pdf</name></item>
        <validationReport jobEndStatus="normal" profileName="PDF/UA-1 validation profile"
                          statement="PDF file is not compliant" isCompliant="false">
          <details passedRules="90" failedRules="3" passedChecks="400" failedChecks="4">
            <rule specification="ISO 14289-1:2014" clause="7.1" testNumber="10"
                  status="failed" failedChecks="1">
              <description>The document catalog dictionary shall include a ViewerPreferences
                dictionary containing a DisplayDocTitle key, whose value shall be true</description>
              <check status="failed"><context>root/document[0]</context></check>
            </rule>
            <rule specification="ISO 14289-1:2014" clause="7.2" testNumber="34"
                  status="failed" failedChecks="2">
              <description>Natural language for text in page content shall be determinable</description>
              <check status="failed"><context>root/document[0]/pages[1]/contentStream[0]</context></check>
            </rule>
            <rule specification="ISO 14289-1:2014" clause="7.4.2" testNumber="1"
                  status="failed" failedChecks="1">
              <description>For documents that are not strongly structured,
                heading tags shall be used in order</description>
              <check status="failed"><context>root/document[0]/pages[0]/H3</context></check>
            </rule>
            <rule specification="ISO 14289-1:2014" clause="7.1" testNumber="3"
                  status="passed" failedChecks="0"><description>passed rule</description></rule>
          </details>
        </validationReport>
      </job></jobs>
    </report>
    """)


def test_parse_mrr_reads_failed_rules_and_pages() -> None:
    failures = parse_mrr(MRR)
    assert [f.rule_id for f in failures] == ["7.1-10", "7.2-34", "7.4.2-1"]
    assert failures[1].pages == [2] and failures[2].pages == [1]


@pytest.fixture
def fake_verapdf(tmp_path, monkeypatch):
    script = tmp_path / "verapdf"
    (tmp_path / "report.xml").write_text(MRR)
    script.write_text(f'#!/bin/sh\ncat "{tmp_path / "report.xml"}"\nexit 1\n')  # 1 = not compliant
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("VERAPDF_PATH", str(script))
    return script


def test_run_verapdf_with_fake_command(fake_verapdf) -> None:
    report = run_verapdf(clean_pdf())
    assert report.available and len(report.failures) == 3


def test_verapdf_results_feed_the_checks(fake_verapdf) -> None:
    pdf = pikepdf.open(io.BytesIO(clean_pdf()))
    del pdf.Root.ViewerPreferences
    data = _save(pdf)
    title_issues = issues_of(title_check.check, data)
    display = next(i for i in title_issues if i.issue_type == "display_doc_title_not_set")
    assert display.sources == ["pikepdf", "veraPDF"] and "7.1-10" in display.suggestion
    lang_issues = issues_of(lang_check.check, data)
    assert types(lang_issues) == {"text_language_not_determinable"} and lang_issues[0].page == 2
    heading_issues = issues_of(headings_check.check, data)
    assert types(heading_issues) == {"heading_rule_failed"}


def test_verapdf_missing_or_disabled(monkeypatch) -> None:
    assert run_verapdf(b"%PDF-1.7").error == "veraPDF is not installed on this server"
    monkeypatch.setenv("VERAPDF_ENABLED", "false")
    assert "turned off" in (run_verapdf(b"%PDF-1.7").error or "")


def test_verapdf_timeout(tmp_path, monkeypatch) -> None:
    script = tmp_path / "verapdf"
    script.write_text("#!/bin/sh\nsleep 5\n")
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("VERAPDF_PATH", str(script))
    monkeypatch.setattr("checks.verapdf.TIMEOUT_SECONDS", 0.5)
    report = run_verapdf(b"%PDF-1.7")
    assert not report.available and "did not finish" in (report.error or "")

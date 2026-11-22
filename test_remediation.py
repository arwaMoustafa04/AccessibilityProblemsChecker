"""Phase 5 repair framework (remediation/) and the CHK-TITLE / CHK-LANG repairs."""

from __future__ import annotations

import base64
import io
import sys
import types

import pikepdf
import pytest

import pipeline
from checks.base import CheckContext, Issue
from checks.headings import label_from_field_name
from remediation import REPAIRERS, RepairAction, RepairContext, ai, apply_repairs, repairer
from remediation.lang import correct_tag, detect_language
from remediation.title import title_from_file_name

ENGLISH = ("The library is open every weekday from eight in the morning until ten at "
           "night. Students can borrow books, reserve study rooms and ask for research "
           "help at the front desk.")
SPANISH = ("La biblioteca abre todos los días laborables desde las ocho de la mañana hasta "
           "las diez de la noche. Los estudiantes pueden pedir libros prestados y reservar "
           "salas de estudio.")


def text_pdf(lines: list[tuple[str, int]], title: str | None = None, lang: str | None = None,
             author: str | None = None) -> bytes:
    """A one-page PDF with the given (text, font size) lines, top to bottom."""
    pdf = pikepdf.new()
    pdf.add_blank_page(page_size=(612, 792))
    page = pdf.pages[0]
    font = pdf.make_indirect(pikepdf.Dictionary(
        Type=pikepdf.Name.Font, Subtype=pikepdf.Name.Type1, BaseFont=pikepdf.Name.Helvetica))
    page.Resources = pikepdf.Dictionary(Font=pikepdf.Dictionary(F1=font))
    y, ops = 720, []
    for text, size in lines:
        safe = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        ops.append(f"BT /F1 {size} Tf 72 {y} Td ({safe}) Tj ET")
        y -= size + 12
    page.Contents = pdf.make_stream("\n".join(ops).encode("latin-1"))
    if title is not None:
        pdf.docinfo["/Title"] = title
    if author is not None:
        pdf.docinfo["/Author"] = author
    if lang is not None:
        pdf.Root.Lang = pikepdf.String(lang)
    buf = io.BytesIO()
    pdf.save(buf)
    return buf.getvalue()


def run(data: bytes, name: str = "upload.pdf"):
    return pipeline.run_pipeline(data, name)


def output(result) -> pikepdf.Pdf:
    return pikepdf.open(io.BytesIO(base64.b64decode(result.output_pdf.content_base64)))


@pytest.fixture(autouse=True)
def repairs_on_no_llm(monkeypatch):
    monkeypatch.setattr(pipeline, "ENABLE_REPAIRS", True)
    monkeypatch.delitem(sys.modules, "llm", raising=False)


@pytest.fixture
def fake_llm(monkeypatch):
    module = types.ModuleType("llm")
    monkeypatch.setitem(sys.modules, "llm", module)
    return module


# --- Language ------------------------------------------------------------------

@pytest.mark.parametrize("raw, fixed", [
    ("en_US", "en-US"), ("EN-us", "en-US"), ("english", "en"), ("Español", "es"),
    ("zh_hans_cn", "zh-Hans-CN"), ("es-419", "es-419"),
])
def test_broken_language_tags_are_corrected(raw, fixed):
    assert correct_tag(raw) == fixed


@pytest.mark.parametrize("raw", ["", "123", "not a language", "x", "xx-YY", "en-US-extra-tags"])
def test_unfixable_language_tags(raw):
    assert correct_tag(raw) is None


def test_language_is_detected_from_text():
    assert detect_language(ENGLISH) == "en"
    assert detect_language(SPANISH) == "es"
    assert detect_language("Hi") is None  # too little text to tell


def test_missing_language_is_detected_and_fixed():
    result = run(text_pdf([("Horario de la biblioteca", 20), (SPANISH[:90], 11),
                           (SPANISH[90:], 11)], title="Horario de la biblioteca"))
    lang = next(f for f in result.findings if f.issue_type == "missing_document_language")
    assert lang.status == "fixed"
    repair = next(r for r in result.repairs if r.finding_id == lang.finding_id)
    assert repair.applied_text == "es" and "detected from the document text" in repair.action
    assert repair.validation_result == "passed"
    with output(result) as pdf:
        assert str(pdf.Root.Lang) == "es"


def test_invalid_language_is_corrected_not_detected():
    result = run(text_pdf([(ENGLISH, 11)], title="Library hours", lang="en_US"))
    repair = next(r for r in result.repairs if "language" in r.action)
    assert repair.applied_text == "en-US" and 'corrected from "en_US"' in repair.action
    with output(result) as pdf:
        assert str(pdf.Root.Lang) == "en-US"


def test_invalid_element_language_is_removed_when_it_cannot_be_corrected():
    pdf = pikepdf.open(io.BytesIO(text_pdf([(ENGLISH, 11)], title="Library hours", lang="en")))
    elem = pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.StructElem,
                                                S=pikepdf.Name.P, Lang=pikepdf.String("??")))
    pdf.Root.StructTreeRoot = pikepdf.Dictionary(Type=pikepdf.Name.StructTreeRoot,
                                                 K=pikepdf.Array([elem]))
    pdf.Root.MarkInfo = pikepdf.Dictionary(Marked=True)
    buf = io.BytesIO()
    pdf.save(buf)
    result = run(buf.getvalue())
    finding = next(f for f in result.findings if f.issue_type == "invalid_element_language")
    assert finding.status == "fixed"
    assert result.new_issues_after_repair == []


# --- Title -----------------------------------------------------------------------

def test_missing_title_uses_largest_heading_on_page_one():
    result = run(text_pdf([("Campus Library Hours", 22), ("Opening times", 14),
                           (ENGLISH, 11)], lang="en"))
    title = next(f for f in result.findings if f.issue_type == "missing_document_title")
    assert title.status == "fixed"
    assert (title.suggested_text, title.suggestion_source) == ("Campus Library Hours", "rule")
    with output(result) as pdf:
        assert str(pdf.docinfo["/Title"]) == "Campus Library Hours"
        meta = pdf.open_metadata()
        assert meta["dc:title"] == "Campus Library Hours"
        assert pdf.Root.ViewerPreferences.DisplayDocTitle is True


def test_placeholder_title_is_replaced_and_other_info_kept():
    result = run(text_pdf([("Quarterly Budget Review", 20), (ENGLISH, 11)],
                          title="Untitled", lang="en", author="Finance team"))
    repair = next(r for r in result.repairs if "Replaced the title" in r.action)
    assert '"Untitled" with "Quarterly Budget Review"' in repair.action
    with output(result) as pdf:
        assert str(pdf.docinfo["/Author"]) == "Finance team"  # untouched by the title fix


def test_good_title_without_xmp_is_left_alone():
    # An Info title without dc:title meets WCAG 2.4.2 (PDF18), so it is not a finding
    # and the title is not touched (titles the repairs write go into both).
    result = run(text_pdf([("Some heading", 20), (ENGLISH, 11)],
                          title="Annual Report 2026", lang="en"))
    assert not [f for f in result.findings if f.check_id == "CHK-TITLE"
                and f.issue_type != "display_doc_title_not_set"]
    with output(result) as pdf:
        assert str(pdf.docinfo["/Title"]) == "Annual Report 2026"


def test_title_falls_back_to_file_name():
    assert title_from_file_name("annual_report-2026.pdf") == "Annual report 2026"
    assert title_from_file_name(".pdf") == "Document"
    result = run(text_pdf([("1", 11)]), "annual_report.pdf")  # text exists, but no usable heading
    with output(result) as pdf:
        assert str(pdf.docinfo["/Title"]) == "Annual report"


def test_ai_title_is_used_labeled_and_noted(fake_llm):
    fake_llm.suggest_title = lambda text, name: 'Title: "Library Hours and Services"'
    result = run(text_pdf([("Campus Library", 22), (ENGLISH, 11)], lang="en"))
    title = next(f for f in result.findings if f.issue_type == "missing_document_title")
    assert (title.suggested_text, title.suggestion_source) == ("Library Hours and Services", "llm")
    repair = next(r for r in result.repairs if r.finding_id == title.finding_id)
    assert repair.method == "llm" and "AI-generated, please verify" in repair.action
    assert title.status == "fixed"
    assert any("sent to an external language model provider" in n for n in result.limitations)


@pytest.mark.parametrize("answer", [None, "", "Untitled", "x" * 300],
                         ids=["none", "empty", "placeholder", "too-long"])
def test_unusable_ai_title_falls_back_to_rules(fake_llm, answer):
    fake_llm.suggest_title = lambda text, name: answer
    result = run(text_pdf([("Campus Library", 22), (ENGLISH, 11)], lang="en"))
    title = next(f for f in result.findings if f.issue_type == "missing_document_title")
    assert (title.suggested_text, title.suggestion_source) == ("Campus Library", "rule")
    assert any("AI title suggestion was not available" in n for n in result.limitations)


def test_llm_error_never_fails_the_request(fake_llm):
    def broken(text, name):
        raise TimeoutError("model too slow")
    fake_llm.suggest_title = broken
    result = run(text_pdf([("Campus Library", 22), (ENGLISH, 11)], lang="en"))
    assert result.status == "completed"
    assert next(r for r in result.repairs if "title" in r.action).method == "rule"


def test_llm_can_be_switched_off(fake_llm, monkeypatch):
    fake_llm.suggest_title = lambda text, name: "Should Not Be Used"
    monkeypatch.setenv("LLM_ENABLED", "false")
    assert not ai.available()
    assert ai.suggest_title(ENGLISH, "a.pdf") is None


def test_ai_title_cleaning():
    assert ai.clean_title('  "Annual Report"  \nextra line') == "Annual Report"
    assert ai.clean_title("Suggested title: **Budget 2026**") == "Budget 2026"
    assert ai.clean_title("ab") is None


# --- Framework -------------------------------------------------------------------

def test_human_review_repair_is_recorded_but_not_resolved(monkeypatch):
    """E.g. AI alt text: written and re-validated, but still for a person to verify."""
    issue = Issue("CHK-NONTEXT", "demo_missing_alt", "Figure has no alt text", page=1,
                  object_ref="Figure 1")

    @repairer("CHK-NONTEXT", "demo_missing_alt")
    def write_alt(issue: Issue, rctx: RepairContext) -> RepairAction:
        return RepairAction("Wrote AI-drafted alt text to Figure 1",
                            applied_text="A bar chart of enrollment", method="llm")

    monkeypatch.setitem(REPAIRERS, ("CHK-NONTEXT", "demo_missing_alt"), write_alt)
    real_evaluate = pipeline.evaluate
    calls = {"n": 0}

    def evaluate(data, file_name, pdf):
        run_, ctx = real_evaluate(data, file_name, pdf)
        calls["n"] += 1
        if calls["n"] == 1:  # before repair: the demo issue is there; after: gone
            run_.issues.append(issue)
        return run_, ctx

    monkeypatch.setattr(pipeline, "evaluate", evaluate)
    result = run(text_pdf([("Heading", 20), (ENGLISH, 11)], title="Library hours", lang="en"))
    finding = next(f for f in result.findings if f.issue_type == "demo_missing_alt")
    repair = next(r for r in result.repairs if r.finding_id == finding.finding_id)
    assert finding.status == "needs_human_review"
    assert finding.finding_id in result.human_review_items
    assert (finding.suggested_text, finding.suggestion_source) == ("A bar chart of enrollment", "llm")
    assert (repair.method, repair.validation_result) == ("llm", "passed")
    assert result.summary.fixed_count == sum(f.status == "fixed" for f in result.findings)


def test_crashing_repair_is_skipped_and_noted(monkeypatch):
    def broken(issue, rctx):
        raise RuntimeError("bug")
    monkeypatch.setitem(REPAIRERS, ("CHK-LANG", "missing_document_language"), broken)
    result = run(text_pdf([(ENGLISH, 11)], title="Library hours"))
    lang = next(f for f in result.findings if f.issue_type == "missing_document_language")
    assert lang.status == "detected"
    assert any("could not be completed (RuntimeError)" in n for n in result.limitations)


def test_apply_repairs_only_runs_registered_repairs():
    pdf = pikepdf.open(io.BytesIO(text_pdf([(ENGLISH, 11)])))
    ctx = CheckContext(b"", "a.pdf", pdf)
    rctx = RepairContext(pdf=pdf, check=ctx, file_name="a.pdf")
    unknown = Issue("CHK-COLOR", "color_only_cue", "Red means required")
    assert apply_repairs([unknown], rctx) == {}


def test_object_numbers_are_matched_after_saving():
    """Saving renumbers objects; re-validation must still see the same link as the same."""
    data = text_pdf([(ENGLISH, 11)])
    before = pikepdf.open(io.BytesIO(data))
    link = before.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.Annot,
                                                   Subtype=pikepdf.Name.Link,
                                                   Rect=pikepdf.Array([0, 0, 10, 10])))
    before.pages[0].Annots = before.make_indirect(pikepdf.Array([link]))
    buf = io.BytesIO()
    before.save(buf)
    after = pikepdf.open(io.BytesIO(buf.getvalue()))
    mapping = pipeline.object_number_map(before, after)
    assert mapping[link.objgen] == after.pages[0].Annots[0].objgen


# --- Hard-coded heading suggestions ---------------------------------------------

@pytest.mark.parametrize("name, label", [
    ("first_name", "First name"), ("emailAddress", "Email address"), ("zip-code", "Zip code"),
    ("Text1", None), ("Check Box 3", None), ("(unnamed)", None), ("7", None),
])
def test_form_label_suggestions(name, label):
    assert label_from_field_name(name) == label


def test_heading_findings_carry_rule_based_suggested_text():
    sys.path.insert(0, "tester")
    from suite import tagged_problems_pdf
    result = run(tagged_problems_pdf(), "tagged_problems.pdf")
    by_type = {f.issue_type: f for f in result.findings if f.check_id == "CHK-HEADINGS"}
    assert by_type["first_heading_not_h1"].suggested_text == "H1"
    assert by_type["heading_level_skipped"].suggested_text == "H3"
    assert by_type["form_field_without_label"].suggested_text == "Name"
    assert all(f.suggestion_source == "rule" for f in by_type.values() if f.suggested_text)
    assert all(f.status == "needs_human_review" for f in by_type.values())

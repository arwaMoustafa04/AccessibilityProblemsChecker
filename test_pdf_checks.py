"""Detection oracles are independent of the implementation's findings."""
import base64
import io
from pathlib import Path

import pikepdf
import pytest
from fastapi.testclient import TestClient

import pipeline
from main import app
from pdf_checks import detect_pdf_issues
from tester.fixtures.pdf_checks.generate import CASES, make_fixture

FIXTURES = Path(__file__).parent / "tester/fixtures/pdf_checks"
EXPECTED = {
    "tagged_image": [], "missing_alt": ["missing_figure_alt"],
    "blank_alt": ["missing_figure_alt"], "untagged_image": ["image_without_text_alternative"],
    "artifact_image": [], "nested_form": [], "inline_image": ["image_without_text_alternative"],
    "missing_structure": ["missing_document_structure"],
    "empty_structure": ["missing_document_structure"], "table_headers": [],
    "table_no_headers": ["table_missing_headers"],
    "combined": ["missing_figure_alt", "table_missing_headers"],
}


def inspect(case, change=None):
    with pikepdf.open(io.BytesIO(make_fixture(case))) as pdf:
        if change:
            change(pdf)
        return detect_pdf_issues(pdf)


@pytest.mark.parametrize("case", CASES)
def test_fixture_oracles_and_reproducibility(case):
    data = make_fixture(case)
    assert data == make_fixture(case) == (FIXTURES / f"{case}.pdf").read_bytes()
    issues = inspect(case)
    assert [i.issue_type for i in issues] == EXPECTED[case]
    assert all(i.page == 1 for i in issues if i.issue_type != "missing_document_structure")


@pytest.mark.parametrize("case", CASES)
def test_endpoint_review_contract(case, monkeypatch):
    monkeypatch.setattr(pipeline, "ENABLE_TITLE_LANG_CHECKS", False)
    data = make_fixture(case)
    response = TestClient(app).post("/process", files={"file": (case + ".pdf", data, "application/pdf")})
    assert response.status_code == 200
    body = response.json()
    findings = body["findings"]
    assert [f["issue_type"] for f in findings] == EXPECTED[case]
    assert body["checks_performed"] == ["CHK-NONTEXT", "CHK-STRUCTURE"]
    assert body["human_review_items"] == [f["finding_id"] for f in findings]
    assert all(f["classification"] == "human_review" and f["status"] == "needs_human_review"
               and f["fix_description"] is None for f in findings)
    for finding in findings:
        expected = "fail" if finding["issue_type"] in {
            "missing_figure_alt", "missing_document_structure"} else "needs_review"
        assert finding["evaluation_result"] == expected
        assert finding["location"]["object_ref"]
    assert body["summary"] == {"total_issues": len(findings), "fixed_count": 0,
                               "human_review_count": len(findings)}
    assert body["repairs"] == body["new_issues_after_repair"] == []
    assert body["outcome"] == "completed_no_repairs"
    assert body["output_pdf"]["modified"] is False
    assert base64.b64decode(body["output_pdf"]["content_base64"]) == data
    with pikepdf.open(io.BytesIO(base64.b64decode(body["report_pdf"]["content_base64"]))) as report:
        assert len(report.pages) >= 1
        text = b"".join(s.read_bytes() for page in report.pages
                        for s in (list(page.Contents) if isinstance(page.Contents, pikepdf.Array)
                                  else [page.Contents]))
        assert b"Checks performed" in text
        for finding in findings:
            assert finding["finding_id"].encode() in text
        assert b"does not certify" in text


def test_role_map_and_inherited_page():
    def custom(pdf):
        doc = pdf.Root.StructTreeRoot.K[0]
        doc.K[0].S = pikepdf.Name.Picture
        pdf.Root.StructTreeRoot.RoleMap = pikepdf.Dictionary(Picture=pikepdf.Name.Figure)
    issues = inspect("missing_alt", custom)
    assert [(i.issue_type, i.page) for i in issues] == [("missing_figure_alt", 1)]


@pytest.mark.parametrize("marked", [False, None])
def test_missing_tagged_marker(marked):
    def change(pdf):
        if marked is None:
            del pdf.Root.MarkInfo
        else:
            pdf.Root.MarkInfo.Marked = marked
    assert [i.issue_type for i in inspect("tagged_image", change)] == ["document_not_marked"]


def test_unused_resources_and_artifact_inside_form():
    def unused(pdf):
        pdf.pages[0].Contents = pdf.make_stream(b"")
    assert inspect("untagged_image", unused) == []

    def artifact(pdf):
        pdf.pages[0].Contents = pdf.make_stream(b"/Artifact BMC /Fm Do EMC")
    assert inspect("nested_form", artifact) == []


def test_repeated_use_and_missing_alt_deduplication():
    def repeat(pdf):
        pdf.pages[0].contents_add(pdf.make_stream(b"/Figure <</MCID 0>> BDC /Im Do /Im Do EMC"))
    assert [i.issue_type for i in inspect("missing_alt", repeat)] == ["missing_figure_alt"]
    def untagged(pdf):
        pdf.pages[0].Contents = pdf.make_stream(b"/Im Do /Im Do")
    assert len(inspect("untagged_image", untagged)) == 2


def test_page_and_stream_mcid_scopes():
    def change(pdf):
        page = pdf.pages[0]
        # MCID 0 belongs to the form only; it cannot supply Alt for a page image.
        page.resources.XObject.Im = page.resources.XObject.Fm.Resources.XObject.Im
        page.contents_add(pdf.make_stream(b"/Figure <</MCID 0>> BDC /Im Do EMC"))
        pdf.add_blank_page()
        pdf.pages[1].resources.XObject = pikepdf.Dictionary(Im=page.resources.XObject.Im)
        pdf.pages[1].Contents = pdf.make_stream(b"/Figure <</MCID 0>> BDC /Im Do EMC")
    assert [i.page for i in inspect("nested_form", change)] == [1, 2]


def test_property_resource_and_inline_artifact():
    def named(pdf):
        page = pdf.pages[0]
        page.resources.Properties = pikepdf.Dictionary(ImageProps=pikepdf.Dictionary(MCID=0))
        page.Contents = pdf.make_stream(b"/Figure /ImageProps BDC /Im Do EMC")
    assert inspect("tagged_image", named) == []
    def artifact(pdf):
        page = pdf.pages[0]
        content = b"\n".join(stream.read_bytes() for stream in page.Contents)
        page.Contents = pdf.make_stream(b"/Artifact BMC " + content + b" EMC")
    assert inspect("inline_image", artifact) == []


def test_table_wrappers_and_nested_headers():
    def wrap(pdf):
        table = pdf.Root.StructTreeRoot.K[0].K[0]
        wrapper = pdf.make_indirect(pikepdf.Dictionary(
            Type=pikepdf.Name.StructElem, S=pikepdf.Name.TBody, P=table, K=table.K))
        for row in table.K:
            row.P = wrapper
        table.K = pikepdf.Array([wrapper])
    assert [i.issue_type for i in inspect("table_no_headers", wrap)] == ["table_missing_headers"]
    def nested(pdf):
        table = pdf.Root.StructTreeRoot.K[0].K[0]
        cell = table.K[0].K[0]
        inner = pdf.make_indirect(pikepdf.Dictionary(
            Type=pikepdf.Name.StructElem, S=pikepdf.Name.Table, P=cell, K=pikepdf.Array()))
        row = pdf.make_indirect(pikepdf.Dictionary(
            Type=pikepdf.Name.StructElem, S=pikepdf.Name.TR, P=inner, K=pikepdf.Array()))
        header = pdf.make_indirect(pikepdf.Dictionary(
            Type=pikepdf.Name.StructElem, S=pikepdf.Name.TH, P=row))
        row.K.append(header)
        inner.K.append(row)
        cell.K = inner
    assert [i.issue_type for i in inspect("table_no_headers", nested)] == ["table_missing_headers"]


@pytest.mark.parametrize("kind", ["tree_cycle", "role_cycle", "bad_child", "bad_parent", "form_cycle",
                                  "bad_stream", "bad_resources"])
def test_incomplete_inspection_is_a_review_finding(kind):
    def change(pdf):
        root = pdf.Root.StructTreeRoot
        doc = root.K[0]
        if kind == "tree_cycle":
            doc.K.append(doc)
        elif kind == "role_cycle":
            root.RoleMap = pikepdf.Dictionary(Figure=pikepdf.Name.Picture, Picture=pikepdf.Name.Figure)
        elif kind == "bad_child":
            doc.K.append("invalid child")
        elif kind == "bad_parent":
            doc.K[0].P = root
        elif kind == "form_cycle":
            form = pdf.pages[0].resources.XObject.Fm
            form.Resources.XObject.Self = form
            form.write(b"/Self Do")
        elif kind == "bad_resources":
            pdf.pages[0].Resources = 42
        else:
            pdf.pages[0].Contents = pdf.make_stream(b"/Missing Do")
    case = "nested_form" if kind == "form_cycle" else "tagged_image"
    issues = inspect(case, change)
    assert any(i.issue_type in {"malformed_structure", "image_inspection_incomplete"}
               and i.evaluation_result == "needs_review" for i in issues)


def test_mixed_repairs_and_review_findings(monkeypatch):
    monkeypatch.setattr(pipeline, "ENABLE_TITLE_LANG_CHECKS", True)
    with pikepdf.open(io.BytesIO(make_fixture("combined"))) as pdf:
        del pdf.docinfo["/Title"]
        del pdf.Root.Lang
        data = io.BytesIO()
        pdf.save(data)
    result = pipeline.run_pipeline(data.getvalue(), "mixed.pdf")
    assert result.summary.total_issues == 4
    assert result.summary.fixed_count == result.summary.human_review_count == 2
    assert len(result.repairs) == 2
    assert all(r.validation_result == "passed" for r in result.repairs)
    assert len(result.human_review_items) == 2
    assert result.new_issues_after_repair == []


def test_inline_image_in_tagged_figure():
    def tag(pdf):
        page = pdf.pages[0]
        doc = pdf.Root.StructTreeRoot.K[0]
        figure = pdf.make_indirect(pikepdf.Dictionary(
            Type=pikepdf.Name.StructElem, S=pikepdf.Name.Figure, P=doc, K=0, Alt="Blue square"))
        doc.K.append(figure)
        content = b"\n".join(s.read_bytes() for s in page.Contents)
        page.Contents = pdf.make_stream(b"/Figure <</MCID 0>> BDC " + content + b" EMC")
    assert inspect("inline_image", tag) == []


def test_revalidation_distinguishes_same_type_at_different_locations(monkeypatch):
    from pdf_checks import Issue
    first = Issue("CHK-TITLE", "missing_document_title", "first", "Title", page=1)
    second = Issue("CHK-TITLE", "missing_document_title", "second", "Title", page=2)
    new = Issue("CHK-NONTEXT", "missing_figure_alt", "new_figure", "Figure", page=1)
    results = iter([[first, second], [second, new]])
    monkeypatch.setattr(pipeline, "ENABLE_TITLE_LANG_CHECKS", True)
    monkeypatch.setattr(pipeline, "detect_issues", lambda pdf: next(results))
    monkeypatch.setattr(pipeline, "repair", lambda *args: {"missing_document_title": "Set title"})
    result = pipeline.run_pipeline(make_fixture("tagged_image"), "same_type.pdf")
    assert [f.status for f in result.findings] == ["fixed", "repair_failed"]
    assert [r.validation_result for r in result.repairs] == ["passed", "failed"]
    assert [f.issue_type for f in result.new_issues_after_repair] == ["missing_figure_alt"]
    assert result.new_issues_after_repair[0].status == "needs_human_review"
    assert result.human_review_items == ["N-1"]


def test_objr_image_association():
    def reference(pdf):
        page = pdf.pages[0]
        figure = pdf.Root.StructTreeRoot.K[0].K[0]
        figure.K = pikepdf.Dictionary(Type=pikepdf.Name.OBJR, Obj=page.resources.XObject.Im)
        page.Contents = pdf.make_stream(b"/Im Do")
    assert inspect("tagged_image", reference) == []


def test_nested_form_missing_alt_is_reported_once():
    def change(pdf):
        del pdf.Root.StructTreeRoot.K[0].K[0].Alt
    assert [i.issue_type for i in inspect("nested_form", change)] == ["missing_figure_alt"]


def test_malformed_pdf_endpoint_remains_reviewable():
    with pikepdf.open(io.BytesIO(make_fixture("tagged_image"))) as pdf:
        doc = pdf.Root.StructTreeRoot.K[0]
        doc.K.append(doc)
        pdf.pages[0].Contents = pdf.make_stream(b"/Missing Do")
        output = io.BytesIO()
        pdf.save(output)
    data = output.getvalue()
    response = TestClient(app).post("/process", files={"file": ("malformed.pdf", data, "application/pdf")})
    assert response.status_code == 200
    body = response.json()
    assert {f["issue_type"] for f in body["findings"]} >= {
        "malformed_structure", "image_inspection_incomplete"}
    assert body["repairs"] == []
    assert base64.b64decode(body["output_pdf"]["content_base64"]) == data

"""veraPDF integration for CHK-NONTEXT and CHK-STRUCTURE (fake veraPDF command)."""

import io
import stat
import textwrap
from pathlib import Path

import pikepdf
import pytest

from checks import nontext, structure
from checks.base import CheckContext

FIXTURES = Path(__file__).parent / "tester" / "fixtures" / "pdf_checks"


def _rule(clause: str, number: str, text: str, page: int | None = None) -> str:
    ctx = f"root/document[0]/pages[{page - 1}]/x" if page else "root/document[0]"
    return (f'<rule specification="ISO 14289-1:2014" clause="{clause}" testNumber="{number}" '
            f'status="failed" failedChecks="1"><description>{text}</description>'
            f'<check status="failed"><context>{ctx}</context></check></rule>')


def install_fake_verapdf(tmp_path: Path, monkeypatch, *rules: str) -> None:
    report = textwrap.dedent(f"""\
        <?xml version="1.0" encoding="utf-8"?>
        <report><jobs><job><validationReport isCompliant="false"><details>
        {"".join(rules)}
        </details></validationReport></job></jobs></report>
        """)
    (tmp_path / "report.xml").write_text(report)
    script = tmp_path / "verapdf"
    script.write_text(f'#!/bin/sh\ncat "{tmp_path / "report.xml"}"\nexit 1\n')
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("VERAPDF_PATH", str(script))
    monkeypatch.delenv("VERAPDF_ENABLED", raising=False)


def run(fn, name: str):
    data = (FIXTURES / name).read_bytes()
    with pikepdf.open(io.BytesIO(data)) as pdf:
        ctx = CheckContext(data, name, pdf)
        try:
            return fn(ctx)
        finally:
            ctx.close()


FIGURE = _rule("7.3", "1", "Figure tags shall include an alternative representation", page=1)
TABLE = _rule("7.5", "1", "Table header cells shall be tagged with TH", page=1)
TAGGED = _rule("7.1", "3", "Content shall be marked as Artifact or tagged as real content", page=1)
TITLE = _rule("7.1", "10", "The document catalog dictionary shall include DisplayDocTitle")


def test_verapdf_confirms_inspector_findings(tmp_path, monkeypatch) -> None:
    install_fake_verapdf(tmp_path, monkeypatch, FIGURE, TABLE)
    alt = run(nontext.check, "missing_alt.pdf")
    assert [i.issue_type for i in alt] == ["missing_figure_alt"]
    assert alt[0].sources == ["pikepdf", "veraPDF"] and "7.3-1" in (alt[0].suggestion or "")
    table = run(structure.check, "table_no_headers.pdf")
    assert [i.issue_type for i in table] == ["table_missing_headers"]
    assert "veraPDF" in table[0].sources


def test_verapdf_adds_rules_the_inspector_missed(tmp_path, monkeypatch) -> None:
    install_fake_verapdf(tmp_path, monkeypatch, FIGURE, TABLE, TAGGED)
    figure = run(nontext.check, "tagged_image.pdf")
    assert [(i.issue_type, i.page, i.evaluation_result) for i in figure] == [
        ("figure_pdfua_rule_failed", 1, "needs_review")]
    found = {i.issue_type for i in run(structure.check, "table_headers.pdf")}
    assert found == {"table_pdfua_rule_failed", "structure_pdfua_rule_failed"}


def test_title_rules_are_not_structure_findings(tmp_path, monkeypatch) -> None:
    install_fake_verapdf(tmp_path, monkeypatch, TITLE)
    assert run(structure.check, "table_headers.pdf") == []


@pytest.mark.parametrize("name", ["tagged_image.pdf", "table_headers.pdf"])
def test_without_verapdf_results_are_unchanged(monkeypatch, name) -> None:
    monkeypatch.setenv("VERAPDF_ENABLED", "false")
    assert run(nontext.check, name) == [] and run(structure.check, name) == []

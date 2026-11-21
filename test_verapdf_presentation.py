"""How veraPDF results show up in findings (review of the Phase 5 output)."""

from __future__ import annotations

from pathlib import Path

import pytest

import pipeline
from checks.base import CheckContext, Issue
from checks.verapdf import RuleFailure, VeraReport, add_advice, cite_rule

FIXTURE = Path(__file__).parent / "tester/fixtures/accessibilityIssues.pdf"
BEFORE = [
    RuleFailure("7.1", "3", "Content shall be tagged or marked as Artifact", [1]),
    RuleFailure("7.1", "11", "StructTreeRoot shall be present"),
    RuleFailure("7.3", "1", "Figure tags shall include an alternative representation", [1]),
    RuleFailure("7.18.5", "1", "Links shall be tagged as Link elements", [1]),
    RuleFailure("7.18.5", "2", "Links shall contain an alternate description", [1]),
]


@pytest.fixture
def fake_verapdf(monkeypatch):
    """veraPDF as on the server; the repaired copy also fails rule 5-1 (identification)."""
    calls = {"n": 0}

    def report(self):
        calls["n"] += 1
        extra = [RuleFailure("5", "1", "PDF/UA identification schema")] if calls["n"] > 1 else []
        return VeraReport(True, BEFORE + extra)

    monkeypatch.setattr(CheckContext, "verapdf", property(report))
    monkeypatch.setattr(pipeline, "ENABLE_REPAIRS", True)
    monkeypatch.setenv("LLM_ENABLED", "false")


def run():
    return pipeline.run_pipeline(FIXTURE.read_bytes(), "accessibilityIssues.pdf")


def test_advice_comes_before_verapdf_citations():
    issue = Issue("CHK-STRUCTURE", "missing_document_structure", "No tags")
    cite_rule(issue, BEFORE[0])
    cite_rule(issue, BEFORE[1])
    add_advice(issue, "Add document tags.")
    assert issue.suggestion == ("Add document tags. (veraPDF PDF/UA-1 rule 7.1-3) "
                                "(veraPDF PDF/UA-1 rule 7.1-11)")
    add_advice(issue, "Add document tags.")  # not repeated
    assert issue.suggestion.count("Add document tags.") == 1


def test_findings_read_advice_first(fake_verapdf):
    for f in run().findings:
        if f.check_id in ("CHK-STRUCTURE", "CHK-NONTEXT"):
            fix = f.fix_description.split("Suggested fix: ", 1)[1]
            assert not fix.startswith("(veraPDF"), fix


def test_verapdf_link_rules_cite_the_existing_link_finding(fake_verapdf):
    links = [f for f in run().findings if f.check_id == "CHK-LINK"]
    assert [f.issue_type for f in links] == ["link_purpose_unclear"]  # one link, one finding
    assert "7.18.5-1" in links[0].fix_description and "7.18.5-2" in links[0].fix_description


def test_identification_rule_is_not_reported_as_a_repair_regression(fake_verapdf):
    result = run()
    assert result.repairs  # the title repair created XMP metadata
    assert not any("veraPDF reports" in n for n in result.limitations)

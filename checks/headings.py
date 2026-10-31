"""CHK-HEADINGS: WCAG 2.4.6 Headings and Labels (human_review).

Whether a heading or label *describes* its topic needs a person, so every finding
here is for human review. The check finds what can be detected automatically:

- text that looks like a heading (PyMuPDF font size/bold) but is not tagged as one
- tagged headings that skip levels, do not start at H1, are empty, or mix H with H1-H6
- form fields with no accessible label (/TU), the "labels" part of 2.4.6
- PDF/UA-1 heading rules reported by veraPDF (clause 7.4)
"""

from __future__ import annotations

from checks.base import CheckContext, Issue
from checks.structure_tree import STANDARD_HEADINGS, iter_elements
from checks.text_layout import lines, probable_headings

CHECK_ID = "CHK-HEADINGS"
MAX_ISSUES_PER_TYPE = 20  # keeps the response readable for very large documents


def _level(tag: str) -> int | None:
    return int(tag[2]) if len(tag) == 3 and tag[2].isdigit() else None


def _heading_issues(ctx: CheckContext) -> list[Issue]:
    issues: list[Issue] = []
    headings = [e for e in iter_elements(ctx) if e.tag in STANDARD_HEADINGS]
    visual = probable_headings(lines(ctx.doc))

    if not headings:
        if visual:
            sample = "; ".join(f'"{h.text[:50]}" (page {h.page})' for h in visual[:3])
            issues.append(Issue(
                CHECK_ID, "headings_not_tagged",
                f"{len(visual)} line(s) look like headings but are not tagged as headings, "
                f"e.g. {sample}.",
                evaluation_result="needs_review", page=visual[0].page,
                suggestion="Tag real headings as H1-H6 in order, and check that each one "
                           "describes the section that follows.",
                sources=["PyMuPDF", "pikepdf"]))
        return issues

    numbered = [h for h in headings if _level(h.tag) is not None]
    if numbered and len(numbered) != len(headings):
        issues.append(Issue(
            CHECK_ID, "mixed_heading_tags",
            "The document mixes generic H tags with numbered H1-H6 tags.",
            evaluation_result="needs_review", page=headings[0].page,
            suggestion="Use one heading scheme, preferably numbered H1-H6.",
            sources=["pikepdf"]))

    if numbered and _level(numbered[0].tag) != 1:
        first = numbered[0]
        issues.append(Issue(
            CHECK_ID, "first_heading_not_h1",
            f"The first heading is {first.tag[1:]}, not H1.",
            evaluation_result="needs_review", page=first.page, object_ref=first.ref,
            suggestion="Start the heading outline at H1.", sources=["pikepdf"]))

    skips = 0
    for prev, cur in zip(numbered, numbered[1:], strict=False):
        a, b = _level(prev.tag), _level(cur.tag)
        if a is not None and b is not None and b > a + 1 and skips < MAX_ISSUES_PER_TYPE:
            skips += 1
            issues.append(Issue(
                CHECK_ID, "heading_level_skipped",
                f"Heading level jumps from {prev.tag[1:]} to {cur.tag[1:]}.",
                page=cur.page, object_ref=cur.ref,
                suggestion=f"Use H{a + 1} here, or add the missing level.", sources=["pikepdf"]))

    for h in [h for h in headings if not h.has_content()][:MAX_ISSUES_PER_TYPE]:
        issues.append(Issue(
            CHECK_ID, "empty_heading", f"A {h.tag[1:]} heading has no content.",
            page=h.page, object_ref=h.ref,
            suggestion="Remove the empty heading or give it descriptive text.",
            sources=["pikepdf"]))
    return issues


def _iter_fields(fields, depth: int = 0):
    for field in fields or []:
        yield field
        if depth < 20 and "/Kids" in field:
            yield from _iter_fields(field.Kids, depth + 1)


def _label_issues(ctx: CheckContext) -> list[Issue]:
    acro = ctx.pdf.Root.get("/AcroForm")
    if acro is None:
        return []
    issues: list[Issue] = []
    for field in _iter_fields(acro.get("/Fields")):
        is_terminal = "/FT" in field or "/Kids" not in field
        if not is_terminal or str(field.get("/TU", "")).strip():
            continue
        if field.get("/Subtype") == "/Widget" and "/T" not in field:
            continue  # a widget of a field already checked through its parent
        name = str(field.get("/T", "")).strip() or "(unnamed)"
        page = ctx.page_of(field.get("/P"))
        issues.append(Issue(
            CHECK_ID, "form_field_without_label",
            f'Form field "{name}" has no accessible label (/TU).',
            page=page, object_ref=f"{field.objgen[0]} {field.objgen[1]} R",
            suggestion="Give the field a label (tooltip) that describes what to enter.",
            sources=["pikepdf"]))
        if len(issues) >= MAX_ISSUES_PER_TYPE:
            break
    return issues


def check(ctx: CheckContext) -> list[Issue]:
    issues = _heading_issues(ctx)
    issues += _label_issues(ctx)
    known = {i.issue_type for i in issues}
    for rule in ctx.verapdf.matching("7.4"):
        if "heading_level_skipped" in known and "level" in rule.description.lower():
            continue
        issues.append(Issue(
            CHECK_ID, "heading_rule_failed", rule.description,
            evaluation_result="needs_review",
            page=rule.pages[0] if rule.pages else None,
            object_ref=f"PDF/UA-1 {rule.rule_id}",
            suggestion=f"Fix the heading structure (veraPDF PDF/UA-1 rule {rule.rule_id}).",
            sources=["veraPDF"]))
    return issues

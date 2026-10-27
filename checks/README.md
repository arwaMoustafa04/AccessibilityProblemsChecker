# Accessibility checks (`checks/`)

`POST /process` runs every check registered in `checks/__init__.py`, in catalog
order, on one opened copy of the PDF. A check only **detects**. Its WCAG criterion,
level and classification (auto_fixable / human_review) come from `catalog.py`.

| Check | File | Uses |
|---|---|---|
| CHK-TITLE (2.4.2) | `title.py` | pikepdf (Info, XMP, ViewerPreferences), PyMuPDF metadata, veraPDF 7.1 |
| CHK-LANG (3.1.1) | `lang.py` | pikepdf (catalog and element /Lang), PyMuPDF (pages with text), veraPDF 7.2 |
| CHK-HEADINGS (2.4.6) | `headings.py` | pikepdf (structure tree, RoleMap, form fields), PyMuPDF (font sizes), veraPDF 7.4 |
| CHK-SENSORY (1.3.3) | `sensory.py` | English instruction/sensory text cues, page locations |
| CHK-COLOR (1.4.1) | `color.py` | English color/meaning cues and multicolor vector graphics |
| CHK-LINK (2.4.4) | `link.py` | Link annotations, visible labels, explicit annotation/Link alternatives |
| CHK-NONTEXT, CHK-STRUCTURE | Person 1: not implemented | |

Person 2 behavior, reproducible PDFs and test expectations are documented in
[`test_fixtures/person2/README.md`](../test_fixtures/person2/README.md). These
three checks only emit `needs_review`, classified as `human_review`, and do not
repair PDFs. They inspect all pages. Their absence of findings is not proof of
accessibility.

## Adding your check

1. Create `checks/<name>.py` with:

   ```python
   from checks.base import CheckContext, Issue

   CHECK_ID = "CHK-LINK"

   def check(ctx: CheckContext) -> list[Issue]:
       issues = []
       for page in ctx.doc:                      # PyMuPDF
           for link in page.get_links():
               ...
               issues.append(Issue(CHECK_ID, "link_text_not_descriptive",
                                   'Link text "click here" does not describe its target.',
                                   evaluation_result="needs_review", page=page.number + 1,
                                   suggestion="Use link text that names the destination.",
                                   sources=["PyMuPDF"]))
       return issues
   ```

2. Register it in `checks/__init__.py`: `from checks import link`, then
   `"CHK-LINK": link.check,` in `CHECK_FUNCTIONS`.
3. Add tests in `test_checks.py` (the builders there make small test PDFs).

What the context gives you:

- `ctx.pdf`: pikepdf `Pdf` (catalog, objects, metadata). Don't modify it.
- `ctx.doc`: PyMuPDF `Document` (text, fonts, images, links, drawings), opened on first use.
- `ctx.verapdf`: veraPDF PDF/UA-1 report, run once on first use and shared by all
  checks. `ctx.verapdf.matching("7.18", "alt")` returns the failed rules in a clause.
  It is empty (with `.error` set) when veraPDF isn't installed, so always keep a
  pikepdf/PyMuPDF path too.
- `structure_tree.iter_elements(ctx)`: every tagged element (tag after RoleMap, page, object).
- `text_layout.lines(ctx.doc)`: text lines with font size and bold.

Issue fields: `issue_type` (snake_case name), `description` (what is wrong),
`evaluation_result` (`"fail"`, or `"needs_review"` when a person must judge),
`page` (1-based), `object_ref`, `suggestion` (how to fix), `sources` (tools used).

If a check raises an exception, `/process` still answers. That check is left out
of `checks_performed`, and `limitations` gives the reason.

## veraPDF

Optional. It is used when the `verapdf` command is on PATH or `VERAPDF_PATH` points
to it (`deploy/setup.sh` installs it to `/opt/verapdf`). Settings:
`VERAPDF_ENABLED=false` turns it off, and `VERAPDF_TIMEOUT_SECONDS` (default 30)
limits each run.

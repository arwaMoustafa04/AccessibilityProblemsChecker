# AccessibilityProblemsChecker

Team 1's implementation of the pod's shared PDF accessibility API.
**The contract is `openapi.yaml` (shared spec v0.3.0).** Both teams build to it,
so if it changes, update it here and send the new version to Team 3.

## Endpoints

Project API (agreed with Team 3):

| Endpoint | What it does |
|---|---|
| `GET /health` | `{"status": "ok", "spec_version": "0.3.0"}` |
| `GET /checks` | `{"checks": [...]}`, the 8 agreed checks with `check_id`, `name`, `wcag_criterion`, `wcag_level`, `classification` |
| `POST /process` | Upload a PDF as the multipart field `file` (plus optional `session_id`). Returns the `EvaluationResult` JSON with the repaired PDF and report PDF in Base64 |

Course test endpoints (required on every system):

| Endpoint | What it does |
|---|---|
| `POST /test/setup` | `{"session_id": "...", "setup": {}}` → 201 with the same ID; 409 if it already exists; 400 if invalid |
| `GET /test/report?session_id=...` | Code coverage (lines of this service run by that session's `/process` calls); 404 for an unknown session |

### What `/process` does today (Phase 3)

- **Input validation is complete:** missing file → 400, over 20 MB → 413,
  not a PDF → 415, corrupted / encrypted / password-protected → 422.
- **CHK-TITLE and CHK-LANG are real:** missing title, `DisplayDocTitle` not set,
  and missing document language are detected, repaired on a copy (title from the
  file name, language `en-US`), and re-validated. The upload is never changed.
- **The six human-review checks are not implemented yet (Phase 4).** They are
  left out of `checks_performed` and named in `limitations`, so an empty
  `findings` list never pretends they were checked.

## Code layout

- `main.py`: HTTP routes and error handling
- `pipeline.py`: validate → detect → repair → re-validate → report
- `catalog.py`: the 8 agreed checks
- `sessions.py`: test sessions and per-session code coverage (in memory; cleared on restart)
- `models.py`: request/response models matching `openapi.yaml`

## Run locally

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-dev.txt
uvicorn main:app --reload
```

Then open `http://localhost:8000/docs`, or try:

```bash
curl -F file=@some.pdf http://localhost:8000/process
```

## Run tests

```bash
python -m pytest
```

Test PDFs are generated in code, so no fixture files are needed.

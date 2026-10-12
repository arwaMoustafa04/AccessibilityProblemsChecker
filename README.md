# AccessibilityProblemsChecker

This service implements the two read-only endpoints needed for the pod's first
URL integration test:

- `GET /health`
- `GET /checks`

The endpoints follow sections 5.1–5.2 of the shared specification:

- `/health` returns `{"status": "ok", "specVersion": "1.0"}`.
- `/checks` returns a JSON array with `checkId`, `name`, `wcagCriterion`,
  `wcagLevel`, and `classification` for each check.

The catalog in `catalog.py` contains CHK-NONTEXT, CHK-STRUCTURE,
CHK-SENSORY, CHK-COLOR, CHK-TITLE, CHK-LINK, CHK-HEADINGS, and CHK-LANG.
Only CHK-TITLE and CHK-LANG are `auto_fixable`; the other six are
`human_review`. CHK-HEADINGS is level AA; the other checks are level A.
These endpoints report service health and the agreed catalog; PDF evaluation
is a separate operation.

## Run locally

```bash
cd AccessibilityProblemsChecker
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-dev.txt
uvicorn main:app --reload
```

Then open:

- `http://localhost:8000/health`
- `http://localhost:8000/checks`
- `http://localhost:8000/docs`
- `http://localhost:8000/openapi.json`

## Run tests

```bash
python -m pytest
```


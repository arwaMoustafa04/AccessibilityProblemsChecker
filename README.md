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
| `POST /evaluations` | Alias of `/process`, with identical upload validation, optional `session_id` coverage, and JSON responses. `/process` remains the canonical shared-contract endpoint |

Course test endpoints (required on every system):

| Endpoint | What it does |
|---|---|
| `POST /test/setup` | `{"session_id": "...", "setup": {}}` → 201 with the same ID; 409 if it already exists; 400 if invalid |
| `GET /test/report?session_id=...` | Code coverage (lines of this service run by that session's `/process` calls); 404 for an unknown session |

### What `/process` does today (Phase 3)

Phase 3 delivers the shared interface only (see the Phase 2 milestone plan:
detection is Phase 4, automatic repair is Phase 5).

- **Input validation is complete:** missing file → 400, over 20 MB → 413,
  not a PDF → 415, corrupted / encrypted / password-protected → 422.
- **A valid PDF gets a well-formed `EvaluationResult` with no checks run:**
  `checks_performed` and `findings` are empty, the PDF comes back unchanged,
  a short report PDF is included, and `limitations` says checks arrive in Phase 4.

Early work for Phases 4-5 (detecting and fixing a missing title and language)
is already in `pipeline.py` but **switched off**. To try it locally:

```bash
ENABLE_TITLE_LANG_CHECKS=true uvicorn main:app --port 8001        # Mac/Linux
set ENABLE_TITLE_LANG_CHECKS=true && uvicorn main:app --port 8001  # Windows cmd
```

Leave it off for anything Team 3 or the graders test until Phase 5.

## The tester (`tester/` folder)

A separate app that runs **our** test suite against **any** pod system (ours or
Team 3's) and returns the course's suite report. Its contract is
`tester/openapi.yaml`.

| Endpoint | What it does |
|---|---|
| `POST /test/setup` | `{"target_url": "<system base URL>"}` → creates a session, calls the target's `/test/setup`, returns 201 `{"session_id": ...}` |
| `POST /test/run` | `{"session_id": ...}` → runs T-01 to T-11, reads the target's `/test/report`, returns the full report |
| `GET /test/report?session_id=...` | Returns the stored report (409 until the run ends) |

The 14 tests (in `tester/suite.py`):

| Test | Checks | Acceptance criteria |
|---|---|---|
| T-01 | `GET /health` returns `status: ok` | — |
| T-02 | `GET /checks` returns the 8 agreed checks and classifications | — |
| T-03 | `goodAccessible.pdf` → 200, no title/language findings, no repairs, both PDFs returned | AC-01, AC-08 |
| T-04 | `accessibilityIssues.pdf` → 200, contract-conforming result | AC-01 |
| T-05 | No compliance claim; fixed non-certification statement | AC-09 |
| T-06 | `NonPDF.docx` → 415 `INVALID_FILE_TYPE` | AC-02 |
| T-07 | No file → 400 `MISSING_FILE` | AC-02 |
| T-08 | Corrupted PDF → 422 | AC-02 |
| T-09 | `encrypted.pdf` → 422 `ENCRYPTED_PDF` | AC-02 |
| T-10 | `passwordProtected.pdf` → 422 `PASSWORD_PROTECTED_PDF` | AC-02 |
| T-11 | Exactly 20 MB + 1 byte → 413 | AC-10 |
| T-12 | Exactly 20 MB → accepted | AC-10 |
| T-13 | `accessibilityIssues.pdf`: 5 built-in issues found and classified (**Phase 4**) | AC-03, AC-04, AC-07 |
| T-14 | `accessibilityIssues.pdf`: title and language fixed and re-validated (**Phase 5**) | AC-05, AC-06, AC-08 |

Files named in the table are the team's shared test set in `tester/fixtures/` (see its
README for each file's expected result). The no-file, corrupted and exact-size cases
are generated in code.

Tests for later phases are reported as `skip` until `CURRENT_PHASE` in
`tester/suite.py` reaches them. In Phase 3 the suite covers 4 of 8 components and
5 of 10 acceptance criteria; detection tests (Phase 4) and repair tests (Phase 5)
raise those numbers.

Run it locally next to the system:

```bash
uvicorn main:app --port 8001                      # the system
cd tester && uvicorn app:app --port 8002          # the tester

curl -X POST localhost:8002/test/setup -H 'content-type: application/json' \
     -d '{"target_url": "http://localhost:8001"}'
curl -X POST localhost:8002/test/run -H 'content-type: application/json' \
     -d '{"session_id": "<id from setup>"}'
```

### Deploying both (AWS)

Run both apps on one EC2 instance behind nginx, which strips the prefix, so the
registered URLs are distinguishable paths on one host:

- System base URL: `https://<host>/system` → `uvicorn main:app --port 8001`
- Tester base URL: `https://<host>/tester` → `uvicorn app:app --port 8002` (from `tester/`)

Set nginx `client_max_body_size 25m;` so 20 MB uploads get through. Don't use
Lambda/API Gateway: their payload limits (6 MB / 10 MB) are below 20 MB.

### Registry "Access / run notes"

No authentication. Maximum times: system setup 10 s; tester setup 15 s;
tester run 12 min worst case (11 project calls × 60 s limit, no retries, plus
coverage retrieval); a normal run takes a few seconds.

## Code layout

- `main.py`: HTTP routes and error handling
- `pipeline.py`: validate → detect → repair → re-validate → report
- `catalog.py`: the 8 agreed checks
- `sessions.py`: test sessions and per-session code coverage (in memory; cleared on restart)
- `models.py`: request/response models matching `openapi.yaml`
- `tester/app.py`: tester endpoints, sessions, report and coverage
- `tester/suite.py`: the 11 test cases and their PDF fixtures

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

## Contract conformance report

Prints, for every operation in `openapi.yaml`, whether it is implemented and whether
its success and error responses match the contract (real requests + schema checks):

```bash
python contract_report.py http://<server-ip>/system     # deployed
python contract_report.py http://localhost:8001         # local
```

## Run tests

```bash
python -m pytest        # system tests and tester tests (tester runs against our system in-process)
```

Test PDFs are generated in code, so no fixture files are needed.

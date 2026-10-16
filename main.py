"""HTTP entry point for the PDF accessibility service (pod shared spec v0.3.0)."""

import logging
import time

from fastapi import FastAPI, File, Form, Query, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from catalog import CHECKS
from models import (
    CheckList,
    Error,
    ErrorCode,
    EvaluationResult,
    Health,
    SessionRef,
    SetupRequest,
    SystemReport,
    TestError,
)
from pipeline import MAX_FILE_SIZE_BYTES, PipelineError, run_pipeline
from sessions import SessionExists, UnknownSession, store

SPEC_VERSION = "0.3.0"

# One line per event on stderr; on the server, systemd sends it to the journal
# (read with: sudo journalctl -u pdf-system).
logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("pdf-system")

app = FastAPI(
    title="Pod PDF Accessibility Evaluation and Remediation API",
    version=SPEC_VERSION,
    description="Team 1 implementation of the pod's shared API (see openapi.yaml).",
)


@app.middleware("http")
async def _log_requests(request: Request, call_next):
    """Log every request with status and processing time; log crashes with a traceback."""
    start = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception:
        log.exception("request method=%s path=%s status=500 crashed",
                      request.method, request.url.path)
        raise
    ms = (time.perf_counter() - start) * 1000
    level = logging.WARNING if response.status_code >= 500 else logging.INFO
    log.log(level, "request method=%s path=%s status=%d duration_ms=%.0f",
            request.method, request.url.path, response.status_code, ms)
    return response


def _error(status: int, code: ErrorCode, message: str) -> JSONResponse:
    return JSONResponse(status_code=status,
                        content=Error(error_code=code, message=message).model_dump())


def _test_error(status: int, message: str) -> JSONResponse:
    return JSONResponse(status_code=status,
                        content=TestError(message=message, source="system").model_dump())


@app.exception_handler(RequestValidationError)
async def _validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
    # FastAPI's default is 422; the course spec and the pod spec both use 400.
    if request.url.path.startswith("/test/"):
        return _test_error(400, "Invalid request: " + "; ".join(
            str(e.get("msg")) for e in exc.errors()))
    return _error(400, "MISSING_FILE", "Request must include a PDF in the 'file' field.")


@app.exception_handler(Exception)
async def _unexpected(request: Request, exc: Exception) -> JSONResponse:
    if request.url.path.startswith("/test/"):
        return _test_error(500, "Unexpected system failure.")
    return _error(500, "PROCESSING_ERROR", "Evaluation could not be completed for this file.")


# --- Project API (pod shared spec) -------------------------------------------

@app.get("/health", response_model=Health, operation_id="getHealth")
def get_health() -> Health:
    """Confirm that the service is reachable and identify its spec version."""
    return Health(status="ok", spec_version=SPEC_VERSION)


@app.get("/checks", response_model=CheckList, operation_id="listChecks")
def list_checks() -> CheckList:
    """Return the pod's agreed check set."""
    return CheckList(checks=list(CHECKS))


@app.post(
    "/evaluations",
    response_model=EvaluationResult,
    operation_id="createEvaluation",
    summary="Alias of POST /process",
    responses={code: {"model": Error} for code in (400, 413, 415, 422, 500, 503)},
)
@app.post(
    "/process",
    response_model=EvaluationResult,
    operation_id="processPdf",
    responses={code: {"model": Error} for code in (400, 413, 415, 422, 500, 503)},
)
def process_pdf(
    file: UploadFile | None = File(None),
    session_id: str | None = Form(None),
):
    """Evaluate a PDF, repair safe issues on a copy, re-validate, and return results."""
    if file is None:
        log.info("process rejected error_code=MISSING_FILE")
        return _error(400, "MISSING_FILE", "Request must include a PDF in the 'file' field.")
    data = file.file.read(MAX_FILE_SIZE_BYTES + 1)
    try:
        with store.measure(session_id):
            result = run_pipeline(data, file.filename or "upload.pdf")
    except PipelineError as err:
        log.info("process rejected error_code=%s size_bytes=%d session=%s",
                 err.error_code, len(data), session_id or "-")
        return _error(err.http_status, err.error_code, err.message)
    log.info("process completed outcome=%s checks=%d findings=%d repairs=%d "
             "size_bytes=%d session=%s", result.outcome, len(result.checks_performed),
             len(result.findings), len(result.repairs), len(data), session_id or "-")
    return result


# --- Course test endpoints (system side) -------------------------------------

@app.post("/test/setup", status_code=201, response_model=SessionRef,
          responses={400: {"model": TestError}, 409: {"model": TestError},
                     500: {"model": TestError}})
def test_setup(body: SetupRequest):
    """Prepare a test session. Nothing needs initializing, so it is ready at once."""
    try:
        store.create(body.session_id)
    except SessionExists:
        log.info("test-setup duplicate session=%s", body.session_id)
        return _test_error(409, f"Session {body.session_id} already exists.")
    log.info("test-setup ready session=%s", body.session_id)
    return SessionRef(session_id=body.session_id)


@app.get("/test/report", response_model=SystemReport,
         responses={400: {"model": TestError}, 404: {"model": TestError}})
def test_report(session_id: str = Query(..., min_length=1)):
    """Code coverage measured for this session's /process requests so far."""
    try:
        code = store.report(session_id)
    except UnknownSession:
        return _test_error(404, f"Unknown session {session_id}.")
    log.info("test-report session=%s code_covered=%s code_total=%s",
             session_id, code["covered"], code["total"])
    return SystemReport.model_validate({"session_id": session_id, "coverage": {"code": code}})

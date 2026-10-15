"""Team 1's tester service (course cross-team testing interface).

POST /test/setup   {"target_url": ...}  -> 201 {"session_id": ...} once the target's setup succeeds
POST /test/run     {"session_id": ...}  -> 200 complete suite report (500 if the tester aborts)
GET  /test/report?session_id=...        -> stored report (409 until the suite ends)

Reports are kept in memory until this tester instance stops.
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from typing import Literal
from urllib.parse import urlsplit

import httpx
from fastapi import FastAPI, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

import suite

SETUP_TIMEOUT_SECONDS = 10.0
REPORT_TIMEOUT_SECONDS = 10.0
SOURCES = {"tester", "system", "communication", "unknown"}

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("pdf-tester")

app = FastAPI(title="Team 1 Tester", version="0.3.0",
              description="Runs Team 1's test suite against a pod system (shared spec v0.3.0).")


def make_client() -> httpx.Client:
    """HTTP client used to reach target systems (replaced in unit tests)."""
    return httpx.Client(follow_redirects=False)


# --- Request bodies ------------------------------------------------------------

class SetupBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    target_url: str = Field(min_length=1)


class RunBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    session_id: str = Field(min_length=1)


def error(status: int, message: str, source: str = "tester") -> JSONResponse:
    log.warning("error status=%d source=%s message=%s", status, source, message)
    return JSONResponse(status_code=status, content={"message": message, "source": source})


@app.exception_handler(RequestValidationError)
async def _bad_request(request: Request, exc: RequestValidationError) -> JSONResponse:
    return error(400, "Invalid request: " + "; ".join(str(e.get("msg")) for e in exc.errors()))


@app.exception_handler(Exception)
async def _unexpected(request: Request, exc: Exception) -> JSONResponse:
    log.error("crash path=%s", request.url.path, exc_info=exc)
    return error(500, f"Tester failure: {type(exc).__name__}.")


# --- Sessions --------------------------------------------------------------------

class Session:
    def __init__(self, session_id: str, target_url: str):
        self.session_id = session_id
        self.target_url = target_url
        self.state: Literal["ready", "running", "ended"] = "ready"
        self.report: dict | None = None


_sessions: dict[str, Session] = {}
_lock = threading.Lock()


def _check_target_url(url: str) -> str | None:
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        return "target_url must be an absolute http(s) URL."
    if parts.username or parts.password:
        return "target_url must not contain credentials."
    if parts.query or parts.fragment:
        return "target_url must not contain a query or fragment."
    if parts.path.rstrip("/").endswith("/test"):
        return "target_url is the system base URL, without the /test suffix."
    return None


# --- POST /test/setup --------------------------------------------------------------

@app.post("/test/setup", status_code=201)
def test_setup(body: SetupBody):
    problem = _check_target_url(body.target_url)
    if problem:
        return error(400, problem)
    target_url = body.target_url.rstrip("/")
    session_id = str(uuid.uuid4())

    try:
        with make_client() as client:
            resp = client.post(f"{target_url}/test/setup",
                               json={"session_id": session_id, "setup": {}},
                               timeout=SETUP_TIMEOUT_SECONDS)
    except httpx.TimeoutException:
        return error(500, f"System setup did not respond within {SETUP_TIMEOUT_SECONDS:.0f} s.",
                     "communication")
    except httpx.HTTPError as exc:
        return error(500, f"Could not reach system setup at {target_url}: {exc}.",
                     "communication")

    if resp.status_code != 201:
        # Forward the system's failure: same status, message and source.
        try:
            payload = resp.json()
        except ValueError:
            payload = {}
        message = payload.get("message") if isinstance(payload, dict) else None
        source = payload.get("source") if isinstance(payload, dict) else None
        return error(resp.status_code,
                     message or f"System setup returned HTTP {resp.status_code}.",
                     source if source in SOURCES else "system")
    try:
        returned = resp.json().get("session_id")
    except (ValueError, AttributeError):
        returned = None
    if returned != session_id:
        return error(500, f"System setup returned 201 but session_id {returned!r} "
                          f"instead of {session_id!r}.", "system")

    with _lock:
        _sessions[session_id] = Session(session_id, target_url)
    log.info("setup ready session=%s target=%s", session_id, target_url)
    return {"session_id": session_id}


# --- POST /test/run ------------------------------------------------------------------

def _code_coverage(client: httpx.Client, session: Session) -> dict:
    url = f"{session.target_url}/test/report"
    try:
        resp = client.get(url, params={"session_id": session.session_id},
                          timeout=REPORT_TIMEOUT_SECONDS)
    except httpx.HTTPError as exc:
        return {"covered": None, "total": None,
                "basis": f"Source lines; system /test/report unreachable ({type(exc).__name__})"}
    if resp.status_code != 200:
        return {"covered": None, "total": None,
                "basis": f"Source lines; system /test/report returned HTTP {resp.status_code}"}
    try:
        code = resp.json()["coverage"]["code"]
        covered, total, basis = code["covered"], code["total"], str(code["basis"]).strip()
    except (ValueError, KeyError, TypeError):
        return {"covered": None, "total": None,
                "basis": "Source lines; system /test/report response was not in the expected format"}
    valid_counts = (covered is None and total is None) or (
        isinstance(covered, int) and isinstance(total, int) and 0 <= covered <= total)
    if not valid_counts or not basis:
        return {"covered": None, "total": None,
                "basis": f"Source lines; system reported invalid counts ({covered}/{total})"}
    return {"covered": covered, "total": total, "basis": f"System-measured: {basis}"}


def _coverage(executed: list[suite.TestCase], code: dict) -> dict:
    components = {c for t in executed for c in t.components}
    criteria = {a for t in executed for a in t.criteria}
    return {
        "code": code,
        "component": {
            "covered": len(components), "total": len(suite.COMPONENTS),
            "basis": "Components listed in the pod specification (openapi.yaml x-pod-testing.components) "
                     "exercised by tests that received a response",
        },
        "system": {
            "covered": len(criteria), "total": len(suite.ACCEPTANCE_CRITERIA),
            "basis": "Acceptance criteria AC-01 to AC-10 listed in the pod specification "
                     "exercised by tests that received a response",
        },
    }


def _report(session: Session, results: list[dict], coverage: dict) -> dict:
    return {"session_id": session.session_id, "target_url": session.target_url,
            "results": results, "coverage": coverage}


@app.post("/test/run")
def test_run(body: RunBody):
    with _lock:
        session = _sessions.get(body.session_id)
        if session is None:
            return error(404, f"Unknown session {body.session_id}.")
        if session.state != "ready":
            return error(409, f"Session {body.session_id} has already run; "
                              "create a new session to repeat the suite.")
        session.state = "running"

    log.info("run started session=%s target=%s", session.session_id, session.target_url)
    started = time.perf_counter()
    results: list[dict] = []
    responded: list[suite.TestCase] = []  # tests that exercised the target
    client = make_client()
    try:
        ctx = suite.Context(client, session.target_url, session.session_id)
        for index, case in enumerate(suite.SUITE):
            if case.phase > suite.CURRENT_PHASE:
                results.append({"test_id": case.test_id, "outcome": "skip",
                                "message": f"Planned for Phase {case.phase}; not run in "
                                           f"Phase {suite.CURRENT_PHASE}."})
                continue
            try:
                message = case.run(ctx)
                results.append({"test_id": case.test_id, "outcome": "pass", "message": message})
                responded.append(case)
            except suite.Mismatch as exc:
                results.append({"test_id": case.test_id, "outcome": "fail", "message": str(exc)})
                responded.append(case)
            except suite.SystemFailure as exc:
                results.append({"test_id": case.test_id, "outcome": "error",
                                "source": "system", "message": str(exc)})
                responded.append(case)
            except httpx.TimeoutException:
                results.append({"test_id": case.test_id, "outcome": "error",
                                "source": "communication",
                                "message": f"The request timed out after "
                                           f"{suite.PROJECT_CALL_TIMEOUT_SECONDS:.0f} s. "
                                           "No response was available to evaluate."})
            except httpx.HTTPError as exc:
                results.append({"test_id": case.test_id, "outcome": "error",
                                "source": "communication",
                                "message": f"No response was available to evaluate "
                                           f"({type(exc).__name__}: {exc})."})
            except Exception as exc:  # a bug in the tester itself: abort the suite
                results.append({"test_id": case.test_id, "outcome": "error", "source": "tester",
                                "message": f"Tester aborted while running this test "
                                           f"({type(exc).__name__}: {exc})."})
                for skipped in suite.SUITE[index + 1:]:
                    results.append({"test_id": skipped.test_id, "outcome": "skip",
                                    "message": "Not executed because the tester aborted."})
                code = {"covered": None, "total": None,
                        "basis": "Source lines; not retrieved because the tester aborted"}
                with _lock:
                    session.report = _report(session, results, _coverage(responded, code))
                    session.state = "ended"
                return error(500, f"Tester aborted during {case.test_id}; "
                                  "retrieve the partial report from /test/report.")
        code = _code_coverage(client, session)
    finally:
        client.close()

    report = _report(session, results, _coverage(responded, code))
    with _lock:
        session.report = report
        session.state = "ended"
    counts = {o: sum(r["outcome"] == o for r in results) for o in ("pass", "fail", "error", "skip")}
    log.info("run finished session=%s pass=%d fail=%d error=%d skip=%d code=%s/%s duration_ms=%.0f",
             session.session_id, counts["pass"], counts["fail"], counts["error"], counts["skip"],
             code["covered"], code["total"], (time.perf_counter() - started) * 1000)
    for r in results:
        if r["outcome"] in ("fail", "error"):
            log.warning("test %s %s source=%s message=%s", r["test_id"], r["outcome"],
                        r.get("source", "-"), r["message"])
    return report


# --- GET /test/report -----------------------------------------------------------------

@app.get("/test/report")
def test_report(session_id: str = Query(..., min_length=1)):
    with _lock:
        session = _sessions.get(session_id)
        if session is None:
            return error(404, f"Unknown session {session_id}.")
        if session.state != "ended":
            return error(409, "The suite has not ended yet; try again later.")
        return session.report

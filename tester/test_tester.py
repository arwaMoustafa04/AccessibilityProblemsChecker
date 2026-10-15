"""Unit tests for the tester, run against Team 1's own system app in-process."""

import sys
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # repo root: system app

import app as tester_app  # noqa: E402
import suite  # noqa: E402
from main import app as system_app  # noqa: E402

TARGET = "http://system.test"
tester = TestClient(tester_app.app)


@pytest.fixture
def target(monkeypatch):
    """Route the tester's outgoing calls to an in-process app (default: our system)."""
    def use(asgi_app=system_app):
        monkeypatch.setattr(tester_app, "make_client", lambda: TestClient(asgi_app))
    use()
    return use


def setup_session() -> str:
    resp = tester.post("/test/setup", json={"target_url": TARGET})
    assert resp.status_code == 201, resp.text
    return resp.json()["session_id"]


def check_report_format(report: dict) -> None:
    assert set(report) == {"session_id", "target_url", "results", "coverage"}
    ids = [r["test_id"] for r in report["results"]]
    assert ids == [t.test_id for t in suite.SUITE]  # every planned test exactly once
    for r in report["results"]:
        assert r["outcome"] in {"pass", "fail", "error", "skip"} and r["message"]
        if r["outcome"] == "error":
            assert r["source"] in {"tester", "system", "communication", "unknown"}
    for name in ("code", "component", "system"):
        c = report["coverage"][name]
        assert c["basis"]
        assert (c["covered"] is None and c["total"] is None) or 0 <= c["covered"] <= c["total"]


def test_full_suite_passes_against_our_system(target) -> None:
    sid = setup_session()
    resp = tester.post("/test/run", json={"session_id": sid})
    assert resp.status_code == 200, resp.text
    report = resp.json()
    check_report_format(report)
    assert report["session_id"] == sid and report["target_url"] == TARGET
    outcomes = {r["test_id"]: r["outcome"] for r in report["results"]}
    assert outcomes.pop("T-04") == "skip"  # Phase 5 test
    assert set(outcomes.values()) == {"pass"}
    cov = report["coverage"]
    # Phase 3 exercises health, catalog, validation and report output only.
    assert (cov["component"]["covered"], cov["component"]["total"]) == (4, 8)
    assert (cov["system"]["covered"], cov["system"]["total"]) == (5, 10)
    assert 0 < cov["code"]["covered"] <= cov["code"]["total"]

    # Stored report is returned unchanged, and the session cannot be run again.
    assert tester.get("/test/report", params={"session_id": sid}).json() == report
    again = tester.post("/test/run", json={"session_id": sid})
    assert again.status_code == 409 and again.json()["source"] == "tester"


def test_report_is_409_before_run(target) -> None:
    sid = setup_session()
    assert tester.get("/test/report", params={"session_id": sid}).status_code == 409


def test_unknown_session_is_404() -> None:
    assert tester.post("/test/run", json={"session_id": "nope"}).status_code == 404
    assert tester.get("/test/report", params={"session_id": "nope"}).status_code == 404


@pytest.mark.parametrize("body", [{}, {"target_url": ""}, {"target_url": "ftp://x"},
                                  {"target_url": "https://user:pw@x.edu/system"},
                                  {"target_url": "https://x.edu/system?a=1"},
                                  {"target_url": "https://x.edu/system/test"}])
def test_invalid_setup_is_400(body) -> None:
    resp = tester.post("/test/setup", json=body)
    assert resp.status_code == 400 and resp.json()["source"] == "tester"


def test_invalid_run_does_not_consume_session(target) -> None:
    sid = setup_session()
    assert tester.post("/test/run", json={}).status_code == 400
    assert tester.post("/test/run", json={"session_id": sid}).status_code == 200


def test_system_setup_failure_is_forwarded(target) -> None:
    broken = FastAPI()

    @broken.post("/test/setup")
    def fail():
        return JSONResponse(status_code=500, content={
            "message": "Could not initialize the session database.", "source": "system"})

    target(broken)
    resp = tester.post("/test/setup", json={"target_url": TARGET})
    assert resp.status_code == 500
    assert resp.json() == {"message": "Could not initialize the session database.",
                           "source": "system"}


def test_unreachable_system_is_communication_error(monkeypatch) -> None:
    def refuse(request):
        raise httpx.ConnectError("connection refused")
    monkeypatch.setattr(tester_app, "make_client",
                        lambda: httpx.Client(transport=httpx.MockTransport(refuse)))
    resp = tester.post("/test/setup", json={"target_url": TARGET})
    assert resp.status_code == 500 and resp.json()["source"] == "communication"


def test_wrong_answers_are_fail_and_crashes_are_system_errors(target) -> None:
    fake = FastAPI()

    @fake.post("/test/setup", status_code=201)
    def setup(body: dict):
        return {"session_id": body["session_id"]}

    @fake.get("/health")
    def health():
        return {"status": "healthy"}  # wrong shape -> fail

    @fake.get("/checks")
    def checks():
        return JSONResponse(status_code=500, content={"detail": "boom"})  # -> error/system

    @fake.post("/process")
    def process():
        return JSONResponse(status_code=400, content={"status": "error",
                                                      "error_code": "MISSING_FILE",
                                                      "message": "no file"})

    @fake.get("/test/report")
    def report(session_id: str):
        return {"session_id": session_id,
                "coverage": {"code": {"covered": None, "total": None,
                                      "basis": "Source lines; target instrumentation unavailable"}}}

    target(fake)
    sid = setup_session()
    report = tester.post("/test/run", json={"session_id": sid}).json()
    check_report_format(report)
    outcomes = {r["test_id"]: (r["outcome"], r.get("source")) for r in report["results"]}
    assert outcomes["T-01"] == ("fail", None)
    assert outcomes["T-02"] == ("error", "system")
    assert outcomes["T-07"] == ("pass", None)  # expected project error -> pass
    assert outcomes["T-06"] == ("fail", None)
    assert report["coverage"]["code"]["covered"] is None


def test_tester_abort_keeps_partial_report(target, monkeypatch) -> None:
    def bug(ctx):
        raise RuntimeError("bug in tester")
    cases = list(suite.SUITE)
    cases[2] = suite.TestCase("T-03", bug, ("COMP-DETECTION",), ("AC-01",))
    monkeypatch.setattr(suite, "SUITE", cases)

    sid = setup_session()
    resp = tester.post("/test/run", json={"session_id": sid})
    assert resp.status_code == 500 and resp.json()["source"] == "tester"
    report = tester.get("/test/report", params={"session_id": sid}).json()
    check_report_format(report)
    outcomes = [r["outcome"] for r in report["results"]]
    assert outcomes[:2] == ["pass", "pass"]
    assert report["results"][2]["outcome"] == "error" and report["results"][2]["source"] == "tester"
    assert set(outcomes[3:]) == {"skip"}
    assert tester.post("/test/run", json={"session_id": sid}).status_code == 409


def test_phase5_suite_passes_with_repairs_enabled(target, monkeypatch) -> None:
    """The early title/language work, switched on, passes the Phase 5 test too."""
    import pipeline
    monkeypatch.setattr(pipeline, "ENABLE_TITLE_LANG_CHECKS", True)
    monkeypatch.setattr(suite, "CURRENT_PHASE", 5)
    sid = setup_session()
    report = tester.post("/test/run", json={"session_id": sid}).json()
    check_report_format(report)
    assert {r["outcome"] for r in report["results"]} == {"pass"}

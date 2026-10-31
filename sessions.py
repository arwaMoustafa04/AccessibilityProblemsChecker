"""Test sessions for the course's /test/setup and /test/report endpoints.

PDFs are never stored. The only state kept between requests is, per session ID,
which source lines of this service ran while handling that session's /process
requests. Sessions live in memory and are cleared when the service restarts.
"""

from __future__ import annotations

import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any

_coverage: Any
try:
    import coverage

    _coverage = coverage
except ImportError:  # coverage is optional; report null counts without it
    _coverage = None

SOURCE_DIR = Path(__file__).resolve().parent
MEASURED_FILES = sorted(  # this service's modules, including the checks/ package
    str(p) for p in [*SOURCE_DIR.glob("*.py"), *SOURCE_DIR.glob("checks/*.py")]
    if not p.name.startswith("test_") and p.name != "conftest.py"
)
BASIS = ("Source lines of this service's Python modules executed while handling "
         "this session's POST /process requests since setup (coverage.py)")
UNAVAILABLE_BASIS = "Source lines; target instrumentation unavailable (coverage.py not installed)"


class SessionExists(Exception):
    pass


class UnknownSession(Exception):
    pass


class SessionStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._measure_lock = threading.Lock()
        self._sessions: dict[str, dict[str, set[int]]] = {}
        self._statements: dict[str, set[int]] | None = None

    def create(self, session_id: str) -> None:
        with self._lock:
            if session_id in self._sessions:
                raise SessionExists(session_id)
            self._sessions[session_id] = {}

    def exists(self, session_id: str) -> bool:
        with self._lock:
            return session_id in self._sessions

    @contextmanager
    def measure(self, session_id: str | None):
        """Record executed lines for a known session; otherwise just run the code."""
        if _coverage is None or not session_id or not self.exists(session_id):
            yield
            return
        with self._measure_lock:  # one measured request at a time
            cov = _coverage.Coverage(data_file=None, include=MEASURED_FILES,
                                     config_file=False)
            cov.start()
            try:
                yield
            finally:
                cov.stop()
                data = cov.get_data()
                with self._lock:
                    lines = self._sessions[session_id]
                    for f in data.measured_files():
                        lines.setdefault(f, set()).update(data.lines(f) or [])
                if self._statements is None:
                    self._statements = {
                        f: set(cov.analysis2(f)[1]) for f in MEASURED_FILES
                    }

    def report(self, session_id: str) -> dict:
        with self._lock:
            if session_id not in self._sessions:
                raise UnknownSession(session_id)
            executed = {f: set(v) for f, v in self._sessions[session_id].items()}
        if _coverage is None:
            return {"covered": None, "total": None, "basis": UNAVAILABLE_BASIS}
        statements = self._statements or self._compute_statements()
        total = sum(len(s) for s in statements.values())
        covered = sum(len(executed.get(f, set()) & s) for f, s in statements.items())
        return {"covered": covered, "total": total, "basis": BASIS}

    def _compute_statements(self) -> dict[str, set[int]]:
        import warnings
        cov = _coverage.Coverage(data_file=None, include=MEASURED_FILES, config_file=False)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")  # "no data collected" is expected here
            cov.start()
            cov.stop()
            cov.get_data()
        self._statements = {f: set(cov.analysis2(f)[1]) for f in MEASURED_FILES}
        return self._statements


store = SessionStore()

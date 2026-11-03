"""Test sessions for the course's /test/setup and /test/report endpoints.

PDFs are never stored. The only state kept between requests is, per session ID,
which source lines of this service ran while handling that session's /process
requests. Sessions live in memory and are cleared when the service restarts.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
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
# Command-line tools kept in the repository that the running service never imports.
NOT_SERVICE_CODE = {"contract_report.py"}
MEASURED_FILES = sorted(  # this service's modules, including the checks/ package
    str(p) for p in [*SOURCE_DIR.glob("*.py"), *SOURCE_DIR.glob("checks/*.py")]
    if not p.name.startswith("test_") and p.name != "conftest.py"
    and p.name not in NOT_SERVICE_CODE
)
BASIS = ("Statements (coverage.py) of this service's Python modules, main.py, pipeline.py, "
         "models.py, catalog.py, sessions.py, pdf_checks.py and checks/*.py, executed for "
         "this session: the lines run while handling its POST /process requests since "
         "setup, plus the lines that run when those modules load (imports, definitions, "
         "models), measured once in a clean interpreter. contract_report.py is a "
         "standalone command-line script, not part of the service, and is not counted")
LOAD_TIMEOUT_SECONDS = 30
_PROBE_ENV = "PDF_SYSTEM_LOAD_PROBE"  # set inside the probe so it never starts another
# Imports the service in a fresh interpreter and prints the lines run while loading.
_LOAD_SCRIPT = """
import json, sys, coverage
files = json.loads(sys.argv[1])
cov = coverage.Coverage(data_file=None, include=files, config_file=False)
cov.start()
import main  # noqa: F401  (loads every service module the app uses)
cov.stop()
data = cov.get_data()
print(json.dumps({f: sorted(data.lines(f) or []) for f in data.measured_files()}))
"""
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
        self._load_lines: dict[str, set[int]] | None = None
        self._load_lock = threading.Lock()

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
        for f, lines in self._module_load_lines().items():
            executed.setdefault(f, set()).update(lines)
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

    def _module_load_lines(self) -> dict[str, set[int]]:
        """Lines that run when the service's modules are imported, measured once.

        These lines (imports, def/class statements, model definitions) run once when
        the service starts, before any session exists, so a per-request measurement
        never sees them. A clean interpreter imports the app under coverage.py to
        find them. If that fails, nothing is added (the older, lower count).
        """
        with self._load_lock:
            if self._load_lines is None:
                self._load_lines = self._measure_module_load()
            return self._load_lines

    def warm_up(self) -> None:
        """Measure the module-load lines in the background, so the first report is fast."""
        if _coverage is not None and not os.environ.get(_PROBE_ENV):
            threading.Thread(target=self._module_load_lines, daemon=True).start()

    @staticmethod
    def _measure_module_load() -> dict[str, set[int]]:
        if os.environ.get(_PROBE_ENV):
            return {}
        try:
            out = subprocess.run(
                [sys.executable, "-c", _LOAD_SCRIPT, json.dumps(MEASURED_FILES)],
                cwd=SOURCE_DIR, capture_output=True, text=True, check=True,
                timeout=LOAD_TIMEOUT_SECONDS, env={**os.environ, _PROBE_ENV: "1"})
            raw = json.loads(out.stdout.strip().splitlines()[-1])
        except (OSError, subprocess.SubprocessError, ValueError, IndexError):
            return {}
        return {f: set(v) for f, v in raw.items() if f in MEASURED_FILES}

store = SessionStore()

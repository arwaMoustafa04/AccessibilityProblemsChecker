"""Run veraPDF (PDF/UA-1 profile) and parse its report.

veraPDF is a Java command-line validator. It is optional: if the ``verapdf``
command is not installed (or VERAPDF_PATH is not set), checks run on pikepdf and
PyMuPDF alone and the response's limitations say veraPDF was not used.

Install on the server: see deploy/setup.sh. The report is read in veraPDF's
"mrr" XML format, which every veraPDF release supports.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field

TIMEOUT_SECONDS = float(os.environ.get("VERAPDF_TIMEOUT_SECONDS", "30"))
_PAGE_RE = re.compile(r"pages\[(\d+)\]")


@dataclass
class RuleFailure:
    clause: str  # PDF/UA-1 (ISO 14289-1) clause, e.g. "7.1"
    test_number: str  # e.g. "10"
    description: str
    pages: list[int] = field(default_factory=list)  # 1-based pages where it failed

    @property
    def rule_id(self) -> str:
        return f"{self.clause}-{self.test_number}"


@dataclass
class VeraReport:
    available: bool
    failures: list[RuleFailure] = field(default_factory=list)
    error: str | None = None  # why veraPDF results are missing, if they are

    def matching(self, clause_prefix: str = "", *words: str) -> list[RuleFailure]:
        """Failed rules in a clause (e.g. "7.4") whose description mentions any word."""
        out = []
        for f in self.failures:
            if clause_prefix and not (f.clause == clause_prefix
                                      or f.clause.startswith(clause_prefix + ".")):
                continue
            if words and not any(w.lower() in f.description.lower() for w in words):
                continue
            out.append(f)
        return out


def verapdf_command() -> str | None:
    return os.environ.get("VERAPDF_PATH") or shutil.which("verapdf")


def parse_mrr(xml_text: str) -> list[RuleFailure]:
    """Failed rules from a veraPDF machine-readable (mrr) XML report."""
    root = ET.fromstring(xml_text)
    failures = []
    for rule in root.iter():
        if not rule.tag.endswith("rule") or rule.get("status") != "failed":
            continue
        desc_el = next((c for c in rule if c.tag.endswith("description")), None)
        pages: set[int] = set()
        for ctx_el in rule.iter():
            if ctx_el.tag.endswith("context") and ctx_el.text:
                m = _PAGE_RE.search(ctx_el.text)
                if m:
                    pages.add(int(m.group(1)) + 1)  # veraPDF counts pages from 0
        failures.append(RuleFailure(
            clause=rule.get("clause", ""),
            test_number=rule.get("testNumber", ""),
            description=(desc_el.text or "").strip() if desc_el is not None else "",
            pages=sorted(pages),
        ))
    return failures


def run_verapdf(data: bytes) -> VeraReport:
    if os.environ.get("VERAPDF_ENABLED", "auto").lower() in ("0", "false", "no"):
        return VeraReport(False, error="veraPDF is turned off (VERAPDF_ENABLED=false)")
    cmd = verapdf_command()
    if not cmd:
        return VeraReport(False, error="veraPDF is not installed on this server")
    with tempfile.NamedTemporaryFile(suffix=".pdf") as tmp:
        tmp.write(data)
        tmp.flush()
        try:
            proc = subprocess.run(
                [cmd, "--flavour", "ua1", "--format", "mrr", tmp.name],
                capture_output=True, text=True, timeout=TIMEOUT_SECONDS, check=False)
        except subprocess.TimeoutExpired:
            return VeraReport(False, error=f"veraPDF did not finish within {TIMEOUT_SECONDS:.0f} s")
        except OSError as exc:
            return VeraReport(False, error=f"veraPDF could not be started: {exc}")
    # veraPDF exits 1 when the file is not compliant; that is a normal result.
    if not proc.stdout.strip().startswith("<"):
        return VeraReport(False, error=f"veraPDF failed (exit code {proc.returncode})")
    try:
        return VeraReport(True, parse_mrr(proc.stdout))
    except ET.ParseError:
        return VeraReport(False, error="veraPDF report could not be read")

"""Response models matching the pod's shared OpenAPI contract (openapi.yaml).

Field names are snake_case, exactly as written in the shared spec.
"""

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class Classification(StrEnum):
    AUTO_FIXABLE = "auto_fixable"
    HUMAN_REVIEW = "human_review"


class WcagLevel(StrEnum):
    A = "A"
    AA = "AA"


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


# --- GET /health -----------------------------------------------------------

class Health(Strict):
    status: Literal["ok"]
    spec_version: str


# --- GET /checks -----------------------------------------------------------

class Check(Strict):
    model_config = ConfigDict(extra="forbid", frozen=True)

    check_id: str
    name: str
    wcag_criterion: str
    wcag_level: WcagLevel
    classification: Classification


class CheckList(Strict):
    checks: list[Check]


# --- POST /process -----------------------------------------------------------

class Location(Strict):
    page: int | None = None
    object_ref: str | None = None
    description: str


FindingStatus = Literal["fixed", "repair_failed", "needs_human_review"]


class Finding(Strict):
    finding_id: str
    check_id: str
    issue_type: str
    wcag_criterion: str
    wcag_level: WcagLevel
    location: Location
    evaluation_result: Literal["fail", "needs_review"]
    classification: Classification
    status: FindingStatus
    fix_description: str | None = None


class Repair(Strict):
    repair_id: str
    finding_id: str
    action: str
    validation_result: Literal["passed", "failed"]


class InputFile(Strict):
    file_name: str
    sha256: str
    size_bytes: int


class OutputFile(Strict):
    file_name: str
    media_type: Literal["application/pdf"] = "application/pdf"
    sha256: str
    modified: bool = False
    content_base64: str


class Summary(Strict):
    total_issues: int
    fixed_count: int
    human_review_count: int


ComplianceStatement = Literal[
    "This report does not certify ADA Title II or WCAG 2.1 conformance."
]
COMPLIANCE_STATEMENT: ComplianceStatement = (
    "This report does not certify ADA Title II or WCAG 2.1 conformance."
)


class EvaluationResult(Strict):
    evaluation_id: str
    status: Literal["completed"] = "completed"
    input: InputFile
    outcome: Literal["completed_with_repairs", "completed_no_repairs"]
    checks_performed: list[str]
    findings: list[Finding]
    repairs: list[Repair]
    new_issues_after_repair: list[Finding]
    human_review_items: list[str]
    summary: Summary
    limitations: list[str]
    compliance_statement: ComplianceStatement = COMPLIANCE_STATEMENT
    output_pdf: OutputFile
    report_pdf: OutputFile


ErrorCode = Literal[
    "MISSING_FILE",
    "INVALID_FILE_TYPE",
    "FILE_TOO_LARGE",
    "CORRUPTED_PDF",
    "UNREADABLE_PDF",
    "ENCRYPTED_PDF",
    "PASSWORD_PROTECTED_PDF",
    "PROCESSING_ERROR",
    "EXTERNAL_SERVICE_UNAVAILABLE",
]


class Error(Strict):
    status: Literal["error"] = "error"
    error_code: ErrorCode
    message: str


# --- Course test endpoints: /test/setup and /test/report ---------------------

class SetupRequest(Strict):
    session_id: str = Field(min_length=1)
    setup: dict = Field(default_factory=dict)


class SessionRef(Strict):
    session_id: str


class CodeCoverage(Strict):
    covered: int | None
    total: int | None
    basis: str


class SystemCoverage(Strict):
    code: CodeCoverage


class SystemReport(Strict):
    session_id: str
    coverage: SystemCoverage


class TestError(Strict):
    message: str = Field(min_length=1)
    source: Literal["tester", "system", "communication", "unknown"] = "system"

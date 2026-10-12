"""HTTP entry point for the PDF accessibility service."""

from fastapi import FastAPI

from catalog import CHECKS
from models import Check, Health


SPEC_VERSION = "1.0"

app = FastAPI(
    title="Pod PDF Accessibility Evaluation and Remediation API",
    version=SPEC_VERSION,
    description="Health and check catalog endpoints for the pod's shared API contract.",
)


@app.get("/health", response_model=Health, operation_id="getHealth")
def get_health() -> Health:
    """Confirm that the service is reachable and identify its spec version."""

    return Health(status="ok", spec_version=SPEC_VERSION)


@app.get("/checks", response_model=list[Check], operation_id="listChecks")
def list_checks() -> list[Check]:
    """Return the accessibility checks exposed by this implementation."""

    return list(CHECKS)

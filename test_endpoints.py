import pytest
from fastapi.testclient import TestClient

from main import app


client = TestClient(app)


def test_health_returns_expected_contract() -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/json"
    assert response.json() == {"status": "ok", "specVersion": "1.0"}


def test_checks_returns_agreed_catalog() -> None:
    response = client.get("/checks")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/json"
    checks = response.json()
    assert isinstance(checks, list)
    assert len(checks) == 8
    # Expected values come from sections 3.1 and 5.2 of the shared specification.
    expected = {
        "CHK-NONTEXT": ("Non-text Content", "1.1.1", "A", "human_review"),
        "CHK-STRUCTURE": ("Info and Relationships", "1.3.1", "A", "human_review"),
        "CHK-SENSORY": ("Sensory Characteristics", "1.3.3", "A", "human_review"),
        "CHK-COLOR": ("Use of Color", "1.4.1", "A", "human_review"),
        "CHK-TITLE": ("Page Titled", "2.4.2", "A", "auto_fixable"),
        "CHK-LINK": ("Link Purpose (In Context)", "2.4.4", "A", "human_review"),
        "CHK-HEADINGS": ("Headings and Labels", "2.4.6", "AA", "human_review"),
        "CHK-LANG": ("Language of Page", "3.1.1", "A", "auto_fixable"),
    }
    assert {check["checkId"] for check in checks} == set(expected)
    for check in checks:
        assert set(check) == {
            "checkId", "name", "wcagCriterion", "wcagLevel", "classification"
        }
        assert (
            check["name"], check["wcagCriterion"],
            check["wcagLevel"], check["classification"],
        ) == expected[check["checkId"]]


@pytest.mark.parametrize("path", ["/health", "/checks"])
def test_endpoint_methods_are_read_only(path: str) -> None:
    assert client.post(path).status_code == 405

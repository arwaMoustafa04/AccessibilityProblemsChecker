"""llm.py (the shared LLM client) and remediation/ai.py, with the network faked."""

from __future__ import annotations

import io
import json
import sys
import urllib.error

import pikepdf
import pytest

import llm
import pipeline
from remediation import ai


class FakeAPI:
    """Stands in for urllib.request.urlopen; answers from a list of responses."""

    def __init__(self, *responses):
        self.responses = list(responses)  # str (answer), int (HTTP error), Exception
        self.requests: list[dict] = []

    def __call__(self, request, timeout):
        body = json.loads(request.data)
        self.requests.append({"url": request.full_url, "body": body, "timeout": timeout,
                              "headers": dict(request.header_items())})
        item = self.responses.pop(0) if self.responses else "default answer"
        if isinstance(item, int):
            raise urllib.error.HTTPError(request.full_url, item, "error", {}, None)
        if isinstance(item, Exception):
            raise item
        payload = {"choices": [{"message": {"content": item}}],
                   "usage": {"prompt_tokens": 10, "completion_tokens": 5}}
        return io.BytesIO(json.dumps(payload).encode())


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for name in ("LLM_API_KEY", "LLM_MOCK", "LLM_ENABLED", "LLM_BASE_URL", "LLM_CACHE_DIR",
                 "LLM_MAX_PER_DAY", "LLM_MAX_PER_MINUTE", "LLM_FALLBACK_MODELS",
                 "LLM_MODEL_TEXT", "LLM_DATA_COLLECTION"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(llm.time, "sleep", lambda s: None)  # no real waiting on retries
    llm.reset_limits()
    sys.modules["llm"] = llm
    yield
    llm.reset_limits()


@pytest.fixture
def api(monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "test-key")
    fake = FakeAPI()
    monkeypatch.setattr(llm.urllib.request, "urlopen", fake)
    return fake


def test_not_configured_makes_no_calls(monkeypatch):
    fake = FakeAPI("never")
    monkeypatch.setattr(llm.urllib.request, "urlopen", fake)
    assert not llm.is_configured() and not ai.available()
    assert llm.suggest_title("Campus Library Hours", "a.pdf") is None
    assert fake.requests == []


def test_successful_call_and_request_shape(api):
    api.responses = ["Campus Library Hours"]
    assert llm.suggest_title("Campus Library Hours\nOpen daily", "hours.pdf") == "Campus Library Hours"
    sent = api.requests[0]
    assert sent["url"] == "https://openrouter.ai/api/v1/chat/completions"
    assert sent["body"]["model"] == llm.DEFAULT_MODEL
    assert sent["body"]["provider"] == {"data_collection": "deny"}  # privacy default
    assert sent["headers"]["Authorization"] == "Bearer test-key"
    user = sent["body"]["messages"][1]["content"][0]["text"]
    assert "<document>" in user and "Campus Library Hours" in user
    assert llm.stats.prompt_tokens == 10


def test_other_providers_get_no_openrouter_fields(api, monkeypatch):
    monkeypatch.setenv("LLM_BASE_URL", "https://integrate.api.nvidia.com/v1")
    api.responses = ["Title"]
    llm.suggest_title("Some text", "a.pdf")
    assert "provider" not in api.requests[0]["body"]


def test_answers_are_cached(api):
    api.responses = ["Campus Library Hours"]
    for _ in range(3):
        assert llm.suggest_title("Campus Library Hours", "a.pdf") == "Campus Library Hours"
    assert len(api.requests) == 1 and llm.stats.cache_hits == 2


def test_disk_cache_survives_a_restart(api, monkeypatch, tmp_path):
    monkeypatch.setenv("LLM_CACHE_DIR", str(tmp_path))
    api.responses = ["Campus Library Hours"]
    llm.suggest_title("Campus Library Hours", "a.pdf")
    llm.reset_limits()  # clears the memory cache, like a service restart
    assert llm.suggest_title("Campus Library Hours", "a.pdf") == "Campus Library Hours"
    assert len(api.requests) == 1


def test_rate_limited_model_is_rested_not_retried(api):
    """429: no immediate retry of the same model; the fallback is tried, and the limited
    model is skipped for later tasks instead of spending the PDF's call budget."""
    api.responses = [429, "Campus Library Hours", "Apply for financial aid"]
    assert llm.suggest_title("Campus Library Hours", "a.pdf") == "Campus Library Hours"
    assert [r["body"]["model"] for r in api.requests] == [
        llm.DEFAULT_MODEL, "nvidia/nemotron-3.5-super-vl:free"]
    assert llm.suggest_link_text("To apply, click here", "https://x.edu/aid")
    assert api.requests[2]["body"]["model"] == "nvidia/nemotron-3.5-super-vl:free"


def test_server_errors_are_still_retried(api):
    api.responses = [503, "Campus Library Hours"]
    assert llm.suggest_title("Campus Library Hours", "a.pdf") == "Campus Library Hours"
    assert [r["body"]["model"] for r in api.requests] == [llm.DEFAULT_MODEL] * 2


def test_no_allowed_provider_skips_that_model_later(api):
    api.responses = [429, 404, 429]  # Gemma busy, Nemotron not allowed by "deny"
    assert llm.suggest_title("Text", "a.pdf") is None
    assert llm.suggest_link_text("Click here", "https://x.edu") is None
    assert len(api.requests) == 2  # second task: both models resting, no calls spent


def test_failing_model_falls_back_to_the_next(api):
    api.responses = [400, "Backup answer"]
    assert llm.suggest_title("Text", "a.pdf") == "Backup answer"
    assert [r["body"]["model"] for r in api.requests] == [
        llm.DEFAULT_MODEL, "nvidia/nemotron-3.5-super-vl:free"]


def test_everything_failing_returns_none(api):
    api.responses = [503, 503, TimeoutError("slow"), TimeoutError("slow")]
    assert llm.suggest_title("Text", "a.pdf") is None
    assert llm.stats.failures == 4


def test_empty_or_odd_answers_are_failures(api, monkeypatch):
    monkeypatch.setenv("LLM_FALLBACK_MODELS", "")
    api.responses = ["   "]
    assert llm.suggest_title("Text", "a.pdf") is None


def test_daily_limit_skips_calls(api, monkeypatch):
    monkeypatch.setenv("LLM_MAX_PER_DAY", "1")
    api.responses = ["One", "Two"]
    assert llm.suggest_title("first", "a.pdf") == "One"
    assert llm.suggest_title("second", "a.pdf") is None
    assert len(api.requests) == 1 and llm.stats.skipped == 1


def test_request_budget_limits_calls_per_pdf(api):
    api.responses = ["One", "Two"]
    with llm.request_budget(seconds=30, calls=1):
        assert llm.suggest_link_text("Click here to apply", "https://x.edu/apply") == "One"
        assert llm.suggest_link_text("Read more about it", "https://x.edu/more") is None
    assert len(api.requests) == 1


def test_request_budget_caps_the_timeout(api):
    api.responses = ["One"]
    with llm.request_budget(seconds=5, calls=4):
        llm.suggest_title("Text", "a.pdf")
    assert api.requests[0]["timeout"] <= 5


def test_image_is_sent_as_a_data_url(api):
    api.responses = ["A bar chart of enrollment by month."]
    assert llm.describe_image(b"\x89PNG fake", "Figure 1", "image/png") == \
        "A bar chart of enrollment by month."
    image = api.requests[0]["body"]["messages"][1]["content"][1]
    assert image["image_url"]["url"].startswith("data:image/png;base64,")


@pytest.mark.parametrize("data, mime", [(b"", "image/png"), (b"x", "image/tiff"),
                                        (b"x" * (llm.MAX_IMAGE_BYTES + 1), "image/png")])
def test_unusable_images_are_not_sent(api, data, mime):
    assert llm.describe_image(data, "", mime) is None
    assert api.requests == []


def test_rewrite_only_for_known_problems(api):
    api.responses = ["Required fields are marked with an asterisk (*)."]
    assert llm.rewrite_sentence("Required fields are in red.", "spelling") is None
    assert llm.rewrite_sentence("Required fields are in red.", "color").startswith("Required")


def test_mock_mode_needs_no_key_or_network(monkeypatch):
    monkeypatch.setenv("LLM_MOCK", "true")
    fake = FakeAPI()
    monkeypatch.setattr(llm.urllib.request, "urlopen", fake)
    assert ai.available() and not ai.sends_data()
    assert llm.suggest_title("Campus Library Hours", "a.pdf") == "Mock title: Campus Library Hours"
    assert llm.describe_image(b"png", "", "image/png")
    assert fake.requests == []


# --- remediation/ai.py cleaning ----------------------------------------------------

def test_ai_cleans_answers(api):
    api.responses = ['  "Image of a bar chart showing enrollment."  ', "DECORATIVE.",
                     '"Apply for financial aid"\nBecause...', "Required fields are in red."]
    assert ai.describe_image(b"png", "", "image/png") == "A bar chart showing enrollment."
    assert ai.describe_image(b"png2", "", "image/png") == ai.DECORATIVE
    assert ai.suggest_link_text("To apply, click here.", "https://x.edu") == "Apply for financial aid"
    # A "rewrite" identical to the original is no suggestion at all.
    assert ai.rewrite_sentence("Required fields are in red.", "color") is None


def test_llm_enabled_false_wins(api, monkeypatch):
    monkeypatch.setenv("LLM_ENABLED", "false")
    assert not ai.available()
    assert ai.suggest_title("Text", "a.pdf") is None and api.requests == []


# --- Pipeline integration ------------------------------------------------------------

def _pdf(title: str | None = None) -> bytes:
    pdf = pikepdf.new()
    pdf.add_blank_page()
    # Valid upload fixtures need extractable text under spec 0.5.0.
    page = pdf.pages[0]
    page.Resources = pikepdf.Dictionary(Font=pikepdf.Dictionary(F1=pdf.make_indirect(
        pikepdf.Dictionary(Type=pikepdf.Name.Font, Subtype=pikepdf.Name.Type1,
                           BaseFont=pikepdf.Name.Helvetica))))
    page.Contents = pdf.make_stream(b"BT /F1 11 Tf 72 700 Td (Sample document text.) Tj ET")
    if title:
        pdf.docinfo["/Title"] = title
    buf = io.BytesIO()
    pdf.save(buf)
    return buf.getvalue()


def test_repairs_are_discarded_if_the_repaired_pdf_cannot_be_rechecked(monkeypatch):
    monkeypatch.setattr(pipeline, "ENABLE_REPAIRS", True)
    real = pipeline.evaluate
    calls = {"n": 0}

    def evaluate(data, file_name, pdf):
        calls["n"] += 1
        if calls["n"] == 2:  # the re-check of the repaired PDF
            raise RuntimeError("broken repaired file")
        return real(data, file_name, pdf)

    monkeypatch.setattr(pipeline, "evaluate", evaluate)
    data = _pdf()
    result = pipeline.run_pipeline(data, "a.pdf")
    assert result.repairs == [] and result.output_pdf.modified is False
    assert any("repairs were discarded" in n for n in result.limitations)
    assert all(f.status != "fixed" for f in result.findings)


def test_new_verapdf_failures_are_reported():
    from checks.base import CheckContext
    from checks.verapdf import RuleFailure, VeraReport
    before = CheckContext(b"", "a.pdf", None)  # type: ignore[arg-type]
    after = CheckContext(b"", "a.pdf", None)  # type: ignore[arg-type]
    before.__dict__["verapdf"] = VeraReport(True, [RuleFailure("7.1", "3", "x")])
    after.__dict__["verapdf"] = VeraReport(True, [RuleFailure("7.1", "3", "x"),
                                                  RuleFailure("7.2", "2", "y")])
    assert pipeline.new_verapdf_failures(before, after) == ["7.2-2"]
    after.__dict__["verapdf"] = VeraReport(False)
    assert pipeline.new_verapdf_failures(before, after) == []


def test_report_pdf_has_before_and_after_summary(monkeypatch):
    import base64

    import pymupdf
    monkeypatch.setattr(pipeline, "ENABLE_REPAIRS", True)
    result = pipeline.run_pipeline(_pdf(), "annual_report.pdf")
    doc = pymupdf.open(stream=base64.b64decode(result.report_pdf.content_base64), filetype="pdf")
    text = " ".join(page.get_text() for page in doc).replace("\n", " ")
    assert "Before and after repair" in text and "fixed and re-validated" in text
    assert "Output PDF: the repaired copy." in text

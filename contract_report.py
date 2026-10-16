"""Print the contract-conformance table for a deployed system.

Usage:
    python contract_report.py http://3.15.117.84/system
    python contract_report.py http://localhost:8001

For every operation in the shared contract (openapi.yaml), it sends real
requests, checks the status code and validates the JSON body against the
contract's schema, and prints one entry per operation in the report format.
"""

from __future__ import annotations

import sys
import uuid
from pathlib import Path

import httpx
import jsonschema
import yaml

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "tester"))
from suite import clean_pdf, make_pdf, pdf_of_exact_size  # noqa: E402  (test fixtures)

SPEC = yaml.safe_load((ROOT / "openapi.yaml").read_text())


def _to_json_schema(node):
    """OpenAPI 3.0 schema -> JSON Schema (nullable, $ref paths)."""
    if isinstance(node, list):
        return [_to_json_schema(n) for n in node]
    if not isinstance(node, dict):
        return node
    node = {k: _to_json_schema(v) for k, v in node.items() if k != "example"}
    if node.pop("nullable", False):
        if "type" in node:
            node["type"] = [node["type"], "null"]
        if "enum" in node:
            node["enum"] = node["enum"] + [None]
    if "$ref" in node:
        node["$ref"] = node["$ref"].replace("#/components/schemas/", "#/$defs/")
    return node


DEFS = _to_json_schema(SPEC["components"]["schemas"])


def conforms(resp: httpx.Response, status: int, schema: str) -> str | None:
    """None if the response matches the contract, else a short difference."""
    if resp.status_code != status:
        return f"expected HTTP {status}, got {resp.status_code}"
    try:
        body = resp.json()
    except ValueError:
        return "body is not JSON"
    try:
        jsonschema.validate(body, {"$defs": DEFS, "$ref": f"#/$defs/{schema}"})
    except jsonschema.ValidationError as exc:
        where = "/".join(str(p) for p in exc.absolute_path) or "body"
        return f"{where}: {exc.message[:80]}"
    return None


def main(base: str) -> int:
    """Print the table; return 1 if any response does not conform (used by CI)."""
    base = base.rstrip("/")
    c = httpx.Client(timeout=60)
    sid = str(uuid.uuid4())

    def process(data, name="t.pdf", path="/process"):
        files = {"file": (name, data, "application/pdf")} if data is not None else None
        return c.post(f"{base}{path}", files=files, data={"session_id": sid})

    def upload_op(path: str, reqs: str):
        """Success and error cases for the upload endpoint."""
        def call(data, name="t.pdf"):
            return lambda: process(data, name, path)
        return (f"POST {path}", reqs,
                [("200", call(clean_pdf()), 200, "EvaluationResult"),
                 ("200 @20 MB", call(pdf_of_exact_size(20_971_520)), 200, "EvaluationResult")],
                [("400", call(None), 400, "Error"),
                 ("413", call(pdf_of_exact_size(20_971_521)), 413, "Error"),
                 ("415", call(b"PK\x03\x04 not a pdf", "a.docx"), 415, "Error"),
                 ("422 corrupted", call(b"%PDF-1.7\n1 0 obj << /Broken"), 422, "Error"),
                 ("422 password", call(make_pdf(user_password="x")), 422, "Error")],
                ["500/503 (cannot be triggered from outside)"])

    setup = lambda body: c.post(f"{base}/test/setup", json=body)  # noqa: E731
    report = lambda **q: c.get(f"{base}/test/report", params=q)  # noqa: E731

    # (method path, requirements, success cases, error cases, untestable errors)
    ops = [
        ("GET /health", "REQ-16",
         [("200", lambda: c.get(f"{base}/health"), 200, "Health")], [], []),
        ("GET /checks", "REQ-03, REQ-05, REQ-06",
         [("200", lambda: c.get(f"{base}/checks"), 200, "CheckList")], [], []),
        ("POST /test/setup", "course testing interface (REQ-16)",
         [("201", lambda: setup({"session_id": sid, "setup": {}}), 201, "SessionRef")],
         [("400", lambda: setup({}), 400, "TestError"),
          ("409", lambda: setup({"session_id": sid}), 409, "TestError")],
         ["500 (no failure path to trigger)"]),
        upload_op("/process", "REQ-01 to REQ-17"),
        ("GET /test/report", "course testing interface (REQ-16)",
         [("200", lambda: report(session_id=sid), 200, "SystemReport")],
         [("400", lambda: report(), 400, "TestError"),
          ("404", lambda: report(session_id="never-created"), 404, "TestError")], []),
    ]

    nonconforming = 0
    print(f"Contract: openapi.yaml v{SPEC['info']['version']}   Target: {base}\n")
    for op, reqs, ok_cases, err_cases, untestable in ops:
        ok_diffs, partial = [], None
        for name, call, status, schema in ok_cases:
            resp = call()
            diff = conforms(resp, status, schema)
            if diff:
                ok_diffs.append(f"{name}: {diff}")
            elif op == "POST /process":
                done = len(resp.json()["checks_performed"])
                if done < 8:
                    partial = f"{done}/8 checks run; detection is Phase 4, repair Phase 5"
        err_diffs = []
        for name, call, status, schema in err_cases:
            diff = conforms(call(), status, schema)
            if diff:
                err_diffs.append(f"{name}: {diff}")

        implemented = "no" if ok_diffs and len(ok_diffs) == len(ok_cases) else (
            f"partial ({partial})" if partial or ok_diffs else "yes")
        ok_text = "yes" if not ok_diffs else "no - " + "; ".join(ok_diffs)
        if not err_cases:
            err_text = "n/a (no error responses defined)"
        elif err_diffs:
            err_text = "no - " + "; ".join(err_diffs)
        else:
            err_text = "yes (" + ", ".join(n for n, *_ in err_cases) + ")"
        if untestable:
            err_text += "; not exercised: " + ", ".join(untestable)
        nonconforming += len(ok_diffs) + len(err_diffs)
        print(f"{op} │ Requirement(s): {reqs} │ Implemented: {implemented}")
        print(f"Success responses conform: {ok_text} │ Error responses conform: {err_text}\n")
    print("RESULT:", "all responses conform" if not nonconforming
          else f"{nonconforming} non-conforming response(s)")
    return 1 if nonconforming else 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    sys.exit(main(sys.argv[1]))

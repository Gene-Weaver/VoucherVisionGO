"""Error envelope foundation: _error_payload / _error_response / ERROR_CODES.

Extracts the real builders from app.py via AST and exercises them directly.
The payload half is dependency-free; the response half needs Flask and is
skipped with a notice when Flask is unavailable.

Run from the repository root:
    python3 tests/tests_error_envelope.py                 # payload tests only
    ./.venv_cors/bin/python tests/tests_error_envelope.py # payload + response
"""
import ast
import io
import os
import sys
import types
from collections import OrderedDict

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = io.open(os.environ.get("VVGO_APP", os.path.join(REPO_ROOT, "app.py")), encoding='utf-8').read()
tree = ast.parse(SRC)


def top_name(n):
    if isinstance(n, (ast.FunctionDef, ast.ClassDef)):
        return n.name
    if isinstance(n, ast.AnnAssign):
        return getattr(n.target, "id", None)
    if isinstance(n, ast.Assign):
        return getattr(n.targets[0], "id", None)
    return None


WANT = ["PAYMENT_INFERENCE_LABELS", "PAYMENT_INFERENCE_NOT_PROCESSED", "RESPONSE_HOST_NAME",
        "_auth_method_for", "resolve_payment_inference", "mark_inference_started",
        "reset_inference_marker", "current_payment_inference", "ERROR_CODES",
        "_ERROR_RESERVED_KEYS", "_error_payload", "_error_response", "_pdf_page_error"]
body = [n for n in tree.body if top_name(n) in WANT]
missing = set(WANT) - {top_name(n) for n in body}
assert not missing, f"missing from app.py: {missing}"


class G:
    """Stand-in for flask.g with no app context bound."""


LOGGED = []
ns = {
    "OrderedDict": OrderedDict,
    "g": G(),
    "logger": types.SimpleNamespace(
        error=lambda *a, **k: LOGGED.append(("error", a)),
        warning=lambda *a, **k: LOGGED.append(("warning", a)),
    ),
    "make_response": lambda body, status=200: ("RESPONSE", body, status),
    "jsonify": lambda payload: payload,
}
exec(compile(ast.Module(body=body, type_ignores=[]), "<app-slice>", "exec"), ns)

payload_of = ns["_error_payload"]
response_of = ns["_error_response"]
mark = ns["mark_inference_started"]
CODES = ns["ERROR_CODES"]
HOST = ns["RESPONSE_HOST_NAME"]
G_OBJ = ns["g"]

fails = 0


def check(label, cond, detail=""):
    global fails
    fails += not cond
    print(f"{'PASS' if cond else 'FAIL'}  {label:<60} {detail}")


def reset_g():
    for attr in ("request_id", "vv_inference_started", "vv_payment_inference",
                 "vv_any_inference_started", "vv_request_payment_inference"):
        if hasattr(G_OBJ, attr):
            delattr(G_OBJ, attr)


print("=== legacy compatibility: `error` prose is never rewritten ===")
reset_g()
p = payload_of("NO_FILE", "No file provided")
check("`error` holds the original prose verbatim", p["error"] == "No file provided", p["error"])
check("`error` is first key (readability)", list(p)[0] == "error", list(p)[:3])
check("error_code added", p["error_code"] == "NO_FILE")
check("host stamped", p["host"] == HOST, p["host"])
check("no message key when none given", "message" not in p, list(p))

p = payload_of("QUOTA_EXHAUSTED", "Rate limit exceeded", message="You have used all 100 ...")
check("message kept distinct from error", p["error"] == "Rate limit exceeded" and
      p["message"].startswith("You have used all"))

print("\n=== closed vocabulary ===")
check("taxonomy is a frozenset (immutable)", isinstance(CODES, frozenset))
check("covers the phases' codes",
      {"UNAUTHENTICATED", "QUOTA_EXHAUSTED", "URL_INVALID", "URL_BLOCKED",
       "UPSTREAM_TIMEOUT", "UPSTREAM_AUTH_FAILED", "INTERNAL_ERROR"} <= CODES)
LOGGED.clear()
p = payload_of("NOT_A_REAL_CODE", "boom")
check("unknown code degrades to INTERNAL_ERROR, never raises",
      p["error_code"] == "INTERNAL_ERROR", p["error_code"])
check("...and is logged", any(l[0] == "error" for l in LOGGED))
check("...while `error` prose survives the fallback", p["error"] == "boom")

print("\n=== payment_inference is only claimed when a provider call began ===")
reset_g()
p = payload_of("INTERNAL_ERROR", "x")
check("absent before any inference call", "payment_inference" not in p, list(p))
reset_g()
G_OBJ.vv_inference_started = True
G_OBJ.vv_payment_inference = "user_supplied_gemini_key"
p = payload_of("UPSTREAM_AUTH_FAILED", "x")
check("present once a call began", p.get("payment_inference") == "user_supplied_gemini_key")
reset_g()
mark(None, None)
check("mark_inference_started sets the server label",
      getattr(G_OBJ, "vv_payment_inference", None) == "VoucherVisionGO_credits")
mark("AQ.key", None)
check("mark_inference_started honors a caller key",
      G_OBJ.vv_payment_inference == "user_supplied_gemini_key")
mark("AQ.key", "proj")
check("vertex wins over a gemini key",
      G_OBJ.vv_payment_inference == "user_supplied_vertex_account")

print("\n=== result envelopes: never claim a payer for work that never ran ===")
current = ns["current_payment_inference"]
reset = ns["reset_inference_marker"]
NOT_RUN = ns["PAYMENT_INFERENCE_NOT_PROCESSED"]
reset_g()
check("no provider call -> not_processed, never a real payer",
      current() == NOT_RUN, current())
check("...and not the server-credits label",
      current() != ns["PAYMENT_INFERENCE_LABELS"]["server"])
mark("AQ.key", None)
check("after a real call -> the actual payer",
      current() == "user_supplied_gemini_key", current())

print("\n=== per-page accuracy: a page cannot inherit the previous page's payer ===")
reset_g()
mark("AQ.key", None)                       # page 1 reached Gemini
check("page 1 reports its payer", current() == "user_supplied_gemini_key")
reset()                                     # page 2 begins
check("page 2 (failed before Gemini) reports not_processed", current() == NOT_RUN, current())
check("request scope still names the real payer, not a server default",
      current(request_scope=True) == "user_supplied_gemini_key",
      current(request_scope=True))
reset_g()
check("a request where nothing ran is not_processed at request scope",
      current(request_scope=True) == NOT_RUN)

print("\n=== nested PDF page failures carry the full envelope ===")
reset_g()
entry = ns["_pdf_page_error"]("p1.jpg", "QUOTA_EXHAUSTED", "cap hit", 503,
                              details={"limit": 100})
check("page entry keeps filename first", list(entry)[0] == "filename", list(entry)[:3])
check("page entry carries error_code", entry["error_code"] == "QUOTA_EXHAUSTED")
check("page entry carries host", entry["host"] == HOST)
check("page entry carries details", entry["details"] == {"limit": 100})
check("page entry keeps status_code", entry["status_code"] == 503)
G_OBJ.request_id = "rid-9"
check("page entry carries request_id",
      ns["_pdf_page_error"]("p.jpg", "INTERNAL_ERROR", "x", 500)["request_id"] == "rid-9")

print("\n=== marker is placed at the provider call, not function entry ===")
fn_ocr = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "perform_ocr")
fn_llm = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)
              and n.name == "process_voucher_vision")
for fn, provider in ((fn_ocr, "ocr_gemini"), (fn_llm, "call_llm_api_GoogleGemini")):
    marks = [c.lineno for c in ast.walk(fn) if isinstance(c, ast.Call)
             and getattr(c.func, "id", "") == "mark_inference_started"]
    calls = [c.lineno for c in ast.walk(fn) if isinstance(c, ast.Call)
             and getattr(c.func, "attr", "") == provider]
    check(f"{fn.name}: marks before {provider}", bool(marks) and bool(calls)
          and min(calls) - max(marks) == 1, f"mark@{marks} call@{calls}")
    check(f"{fn.name}: marker is not at function entry",
          bool(marks) and min(marks) - fn.lineno > 3, f"fn@{fn.lineno} mark@{marks}")

print("\n=== request correlation (populated by the next phase) ===")
reset_g()
check("request_id omitted when unset", "request_id" not in payload_of("INTERNAL_ERROR", "x"))
G_OBJ.request_id = "abc-123"
check("request_id included when set", payload_of("INTERNAL_ERROR", "x")["request_id"] == "abc-123")

print("\n=== legacy fields merge, but cannot shadow the envelope ===")
reset_g()
p = payload_of("QUOTA_EXHAUSTED", "Rate limit exceeded",
               legacy={"gemini_pro_usage_count": 100, "gemini_pro_usage_limit": 100})
check("legacy fields land at top level", p["gemini_pro_usage_count"] == 100)
LOGGED.clear()
p = payload_of("QUOTA_EXHAUSTED", "real prose",
               legacy={"error": "HIJACKED", "error_code": "NOPE", "host": "evil"})
check("legacy cannot overwrite `error`", p["error"] == "real prose", p["error"])
check("legacy cannot overwrite error_code", p["error_code"] == "QUOTA_EXHAUSTED")
check("legacy cannot overwrite host", p["host"] == HOST)
check("shadowing attempts are logged", any(l[0] == "warning" for l in LOGGED))

print("\n=== details ===")
p = payload_of("QUOTA_EXHAUSTED", "x", details={"count": 100, "limit": 100})
check("details nested, not flattened", p["details"] == {"count": 100, "limit": 100})
check("details omitted when empty", "details" not in payload_of("INTERNAL_ERROR", "x"))

print("\n=== helper/route contract separation ===")
check("_error_payload returns a plain dict (helpers return (dict, status))",
      isinstance(payload_of("NO_FILE", "x"), dict))
def code_of(fn_name):
    """Source of a function with its docstring removed, so prose in comments
    and docstrings cannot satisfy (or break) a code-level assertion."""
    fn = next(n for n in tree.body if top_name(n) == fn_name)
    stmts = fn.body[1:] if (fn.body and isinstance(fn.body[0], ast.Expr)
                            and isinstance(fn.body[0].value, ast.Constant)
                            and isinstance(fn.body[0].value.value, str)) else fn.body
    return "\n".join(ast.get_source_segment(SRC, st) or "" for st in stmts)

code_resp, code_pay = code_of("_error_response"), code_of("_error_payload")
check("_error_response writes no CORS header", "Access-Control" not in code_resp)
check("_error_payload writes no CORS header", "Access-Control" not in code_pay)
check("_error_payload builds no Flask response",
      "jsonify" not in code_pay and "make_response" not in code_pay)

try:
    from flask import Flask, jsonify as real_jsonify, make_response as real_make_response
except ImportError:
    print("\n=== Flask response form: SKIPPED (Flask not installed) ===")
else:
    print("\n=== Flask response form ===")
    ns2 = dict(ns)
    ns2["jsonify"] = real_jsonify
    ns2["make_response"] = real_make_response
    exec(compile(ast.Module(body=[n for n in body if top_name(n) in ("_error_payload", "_error_response")],
                            type_ignores=[]), "<app-slice>", "exec"), ns2)
    app = Flask(__name__)
    with app.test_request_context():
        resp = ns2["_error_response"]("NO_FILE", "No file provided", status=400)
        check("returns a real Flask Response", hasattr(resp, "status_code"))
        check("honors the status argument", resp.status_code == 400, str(resp.status_code))
        check("content type is JSON", resp.mimetype == "application/json", resp.mimetype)
        data = resp.get_json()
        check("body carries the envelope", data["error"] == "No file provided"
              and data["error_code"] == "NO_FILE" and data["host"] == HOST)
        check("no CORS header written by the helper",
              not any(k.startswith("Access-Control") for k, _ in resp.headers))
        check("default status is 500",
              ns2["_error_response"]("INTERNAL_ERROR", "x").status_code == 500)

print(f"\n{'ALL PASS' if not fails else str(fails) + ' FAILED'}")
sys.exit(1 if fails else 0)

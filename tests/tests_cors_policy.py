"""CORS policy tests driven by the REAL app.py source.

app.py cannot be imported (heavy deps), so this extracts its actual CORS
configuration and request hooks via AST and mounts them on a bare Flask app.
Run from the repository root:  ./.venv_cors/bin/python tests/tests_cors_policy.py
"""
import ast, io, os, sys
from flask import Flask, request, make_response, jsonify
from flask_cors import CORS

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = io.open(os.environ.get("VVGO_APP", os.path.join(REPO_ROOT, "app.py")), encoding='utf-8').read()
tree = ast.parse(SRC)

# 1. No hand-written Access-Control-* writes may survive anywhere in app.py.
manual = [(i, l.strip()) for i, l in enumerate(SRC.split('\n'), 1)
          if 'Access-Control' in l and ('headers.add' in l or 'headers[' in l)]

# 2. Pull the real CORS(app, ...) kwargs and the real hooks out of the source.
cors_call = next(n for n in ast.walk(tree)
                 if isinstance(n, ast.Call) and getattr(n.func, 'id', '') == 'CORS')
kw = {k.arg: ast.literal_eval(k.value) for k in cors_call.keywords
      if k.arg and isinstance(k.value, (ast.List, ast.Constant, ast.Tuple))}
consts = {}
for n in tree.body:
    if isinstance(n, ast.Assign) and getattr(n.targets[0], 'id', '') in (
            "CORS_ALLOWED_HEADERS", "CORS_EXPOSED_HEADERS"):
        consts[n.targets[0].id] = ast.literal_eval(n.value)
for k in ("allow_headers", "expose_headers"):
    node = next((c.value for c in cors_call.keywords if c.arg == k), None)
    if isinstance(node, ast.Name):
        kw[k] = consts[node.id]

preflight = next(n for n in ast.walk(tree)
                 if isinstance(n, ast.FunctionDef) and n.name == "begin_request")
billing = next(n for n in ast.walk(tree)
               if isinstance(n, ast.FunctionDef) and n.name == "_add_correlation_headers")
for f in (preflight, billing):
    f.decorator_list = []

app = Flask(__name__)
CORS(app, **kw)
from flask import g as flask_g
ns = {"request": request, "make_response": make_response, "g": flask_g,
      "uuid": __import__("uuid"),
      "_check_api_key_expirations": lambda: None, "getattr": getattr}
exec(compile(ast.Module(body=[preflight, billing], type_ignores=[]), "<slice>", "exec"), ns)
app.before_request(ns["begin_request"])
app.after_request(ns["_add_correlation_headers"])

@app.route('/process', methods=['POST', 'OPTIONS'])
def process():
    return make_response(jsonify({'ok': True}), 200)

fails = 0
def check(label, cond, detail=""):
    global fails; fails += not cond
    print(f"{'PASS' if cond else 'FAIL'}  {label:<58} {detail}")

print("=== single-writer invariant ===")
check("no hand-written Access-Control-* writes in app.py", not manual,
      f"{len(manual)} found" if manual else "")
check("policy declares the billing headers",
      all(h in kw.get("allow_headers", []) for h in
          ("X-Gemini-API-Key", "X-Vertex-Project", "X-Vertex-Region")))
check("policy exposes X-VV-Billing-Mode and X-Request-ID",
      set(kw.get("expose_headers", [])) >= {"X-VV-Billing-Mode", "X-Request-ID"},
      str(kw.get("expose_headers")))

c = app.test_client()
ORIG = "https://leafmachine.org"

print("\n=== real OPTIONS preflight ===")
for hdr in ("X-Gemini-API-Key", "X-Vertex-Project", "X-Vertex-Region", "X-API-Key", "Content-Type"):
    r = c.open('/process', method='OPTIONS', headers={
        "Origin": ORIG, "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": hdr})
    allowed = " ".join(r.headers.getlist("Access-Control-Allow-Headers")).lower()
    check(f"preflight allows {hdr}", hdr.lower() in allowed, f"{r.status_code}")

r = c.open('/process', method='OPTIONS', headers={
    "Origin": ORIG, "Access-Control-Request-Method": "POST",
    "Access-Control-Request-Headers": "X-Gemini-API-Key"})
check("preflight is 2xx", 200 <= r.status_code < 300, str(r.status_code))
for h in ("Access-Control-Allow-Origin", "Access-Control-Allow-Headers",
          "Access-Control-Allow-Methods", "Access-Control-Allow-Credentials"):
    check(f"exactly one {h}", len(r.headers.getlist(h)) == 1,
          str(r.headers.getlist(h)))
check("preflight echoes the Origin (not '*')",
      r.headers.get("Access-Control-Allow-Origin") == ORIG,
      r.headers.get("Access-Control-Allow-Origin"))
check("preflight sets max-age", r.headers.get("Access-Control-Max-Age") == "3600",
      r.headers.get("Access-Control-Max-Age"))

print("\n=== credentialed CORS is valid (no wildcard + credentials) ===")
r = c.post('/process', headers={"Origin": ORIG})
acao = r.headers.getlist("Access-Control-Allow-Origin")
check("actual response echoes Origin", acao == [ORIG], str(acao))
check("Allow-Credentials: true", r.headers.get("Access-Control-Allow-Credentials") == "true")
check("never wildcard while credentials are allowed",
      not (r.headers.get("Access-Control-Allow-Credentials") == "true" and "*" in acao))
check("Vary: Origin present (cache safety)", "Origin" in r.headers.get("Vary", ""),
      r.headers.get("Vary"))
check("exposes X-VV-Billing-Mode to the browser",
      "X-VV-Billing-Mode" in r.headers.get("Access-Control-Expose-Headers", ""),
      r.headers.get("Access-Control-Expose-Headers"))

print("\n=== non-browser callers are unaffected ===")
r = c.post('/process')
check("no Origin -> request still succeeds", r.status_code == 200, str(r.status_code))
check("no Origin -> no duplicate CORS headers",
      len(r.headers.getlist("Access-Control-Allow-Origin")) <= 1)

print("\n=== disallowed origin ===")
r = c.post('/process', headers={"Origin": "https://evil.test"})
check("wildcard policy still allows any origin (documented behavior)",
      r.headers.get("Access-Control-Allow-Origin") == "https://evil.test",
      r.headers.get("Access-Control-Allow-Origin"))

print("\n=== request correlation ===")
# The ID must be assigned before the OPTIONS early-return, or preflight
# responses never receive one.
stmts = preflight.body[1:] if (preflight.body and isinstance(preflight.body[0], ast.Expr)
                               and isinstance(preflight.body[0].value, ast.Constant)) else preflight.body
first_if = next((i for i, st in enumerate(stmts) if isinstance(st, ast.If)), len(stmts))
assigns = [i for i, st in enumerate(stmts) if "request_id" in (ast.get_source_segment(SRC, st) or "")]
check("request_id assigned before the OPTIONS early-return",
      bool(assigns) and min(assigns) < first_if, f"assign@{assigns} if@{first_if}")

r = c.open('/process', method='OPTIONS', headers={
    "Origin": ORIG, "Access-Control-Request-Method": "POST",
    "Access-Control-Request-Headers": "X-Gemini-API-Key"})
rid_pre = r.headers.get("X-Request-ID")
check("preflight response carries X-Request-ID", bool(rid_pre), str(rid_pre))
r2 = c.post('/process', headers={"Origin": ORIG})
rid_post = r2.headers.get("X-Request-ID")
check("normal response carries X-Request-ID", bool(rid_post), str(rid_post))
check("IDs differ between requests", rid_pre != rid_post)
check("X-Request-ID exposed to browsers",
      "X-Request-ID" in r2.headers.get("Access-Control-Expose-Headers", ""),
      r2.headers.get("Access-Control-Expose-Headers"))
check("non-CORS caller also gets X-Request-ID", bool(c.post('/process').headers.get("X-Request-ID")))

print(f"\n{'ALL PASS' if not fails else str(fails)+' FAILED'}")
sys.exit(1 if fails else 0)

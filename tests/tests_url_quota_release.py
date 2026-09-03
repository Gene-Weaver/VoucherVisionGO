"""Behavioral test: /process-url must release reserved quota on every failure path.

Execs the real process_image_by_url out of app.py with stubs for Flask, the
processor and Firestore, then drives each failure path and asserts the
reservation is returned.
"""
import os
import ast, io, sys, types
from collections import OrderedDict

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = io.open(os.environ.get("VVGO_APP", os.path.join(REPO_ROOT, "app.py")), encoding='utf-8').read()
tree = ast.parse(SRC)
fn = next(n for n in ast.walk(tree)
          if isinstance(n, ast.FunctionDef) and n.name == "process_image_by_url")
fn.decorator_list = []   # drop @app.route / @authenticated_route

STATE = {}
def reset():
    STATE.clear()
    STATE.update(reserved=[], released=[], processed=False)

class Resp:
    def __init__(self, body, status=200): self.body, self.status_code, self.headers = body, status, Hdr()
class Hdr(dict):
    def add(self, k, v): self[k] = v
    def get(self, k, d=None): return dict.get(self, k, d)

def jsonify(*a, **k): return Resp(a[0] if a else k)
def make_response(body, status=200): return Resp(body, status)

class Req:
    is_json = False
    method = "POST"
    form = {"image_url": "http://x/img.jpg"}
    args, headers, files, cookies = {}, Hdr(), {}, {}
    def get_json(self, silent=False): return None

FAIL_MODE = {"mode": "fetch"}

# The route fetches via smart_fetch_image_as_filestorage, with a bare
# `except:` fallback to process_url_image_with_resize. Path A (the
# fetch-failure envelope) needs BOTH to raise RequestException; path B (the
# in-loop `except Exception`) needs the fallback to raise something else.
def fake_smart(*a, **kw):
    raise IOError("connection refused")

def fake_resize(*a, **kw):
    if FAIL_MODE["mode"] == "fetch":
        raise IOError("connection refused")   # RequestException -> path A
    raise ValueError("kaboom in resize")      # generic -> path B

ns = {
    "jsonify": jsonify, "make_response": make_response, "request": Req(),
    "OrderedDict": OrderedDict, "json": __import__("json"), "time": types.SimpleNamespace(sleep=lambda s: None),
    "uuid": __import__("uuid"), "logger": types.SimpleNamespace(**{k: (lambda *a, **kw: None) for k in
        ("info","error","warning","exception","debug")}),
    "requests": types.SimpleNamespace(exceptions=types.SimpleNamespace(RequestException=IOError)),
    "smart_fetch_image_as_filestorage": fake_smart,
    "process_url_image_with_resize": fake_resize,
    "os": __import__("os"), "APP_USER_AGENT": "test/1.0",
    "get_user_email_from_request": lambda r: "u@x.edu",
    "get_payment_auth_context": lambda r: {"gemini_api_key": None, "vertex_project": None,
                                           "vertex_region": None, "auth_method": "server"},
    "_billing_intent_error_response": lambda r: None,
    "_validate_vertex_params": lambda *a: (None, None),
    "_validate_vertex_project_id": lambda p: (p, None),
    "_validate_vertex_project_binding": lambda p, e: None,
    "resolve_model_defaults": None,   # filled below with the REAL one
    "build_request_analytics_context": lambda *a, **k: {"request_id": "rid"},
    "_preflight_user_prompt": lambda p, e: (None, None),
    "rate_limited_keys_in_request": lambda e, l: ["gemini-3.1-flash-lite"],
    "quota_keys_for_request": lambda e, l, ocr_only=False, notebook_mode=False: ["gemini-3.1-flash-lite"],
    "check_and_reserve_quotas": lambda e, keys: (STATE["reserved"].extend(keys) or True,
                                                 {k: (1, 5) for k in keys}, None),
    "release_quotas": lambda e, keys: STATE["released"].extend(keys),
    "_rate_limit_field_prefix": lambda k: "gemini_general_access",
    "GEMINI_GENERAL_ACCESS_PREFIX": "gemini_general_access",
    "_send_general_access_cap_alert": lambda *a, **k: None,
    "_send_rate_limit_hit_alert": lambda *a, **k: None,
    "_send_pro_migration_advisory": lambda *a, **k: None,
    "read_rate_limit_state": lambda e: {},
    "build_usage_event": lambda **k: {"success": True},
    "persist_usage_events_and_rollups": lambda *a, **k: None,
    "record_usage_event": lambda e: None,
    "extract_filename_from_url": lambda u: "img.jpg",
    "resolve_payment_inference": lambda k=None, p=None: "VoucherVisionGO_credits",
    "RESPONSE_HOST_NAME": "VoucherVisionGO",
    "OrderedJsonEncoder": __import__("json").JSONEncoder,
    "app": types.SimpleNamespace(config={"processor": None}),
}
# use the real resolver so defaults+quota interaction is exercised end to end
real = next(n for n in tree.body if getattr(n, "name", None) == "resolve_model_defaults")
dm  = next(n for n in tree.body if isinstance(n, ast.Assign) and getattr(n.targets[0], "id", "") == "DEFAULT_MODEL")
am  = next(n for n in tree.body if isinstance(n, ast.Assign) and getattr(n.targets[0], "id", "") == "API_TO_COST_MAPPING")
exec(compile(ast.Module(body=[dm, am, real], type_ignores=[]), "<slice>", "exec"), ns)
exec(compile(ast.Module(body=[fn], type_ignores=[]), "<slice>", "exec"), ns)
route = ns["process_image_by_url"]

fails = 0
def check(label, cond, detail=""):
    global fails; fails += not cond
    print(f"{'PASS' if cond else 'FAIL'}  {label:<56} {detail}")

# Path A: every download retry fails -> the fetch-failure envelope.
reset(); FAIL_MODE["mode"] = "fetch"
route()
check("A. total fetch failure reserved a slot", STATE["reserved"] == ["gemini-3.1-flash-lite"], f"{STATE['reserved']}")
check("A. total fetch failure RELEASES the slot", STATE["released"] == STATE["reserved"], f"released={STATE['released']}")

# Path B: unexpected exception inside the retry loop.
reset(); FAIL_MODE["mode"] = "unexpected"
route()
check("B. in-loop unexpected error reserved a slot", STATE["reserved"] == ["gemini-3.1-flash-lite"], f"{STATE['reserved']}")
check("B. in-loop unexpected error RELEASES the slot", STATE["released"] == STATE["reserved"], f"released={STATE['released']}")

print(f"\n{'ALL PASS' if not fails else str(fails)+' FAILED'}")
sys.exit(1 if fails else 0)

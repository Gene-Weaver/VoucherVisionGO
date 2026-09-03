"""Behavioral tests for PDF per-page quota metering and reservation release.

Execs the real process_pdf_request / _reserve_pdf_page_quota_if_needed out of
app.py and drives them with stubs. No GCP boot required.
"""
import os
import ast, io, os, sys, types
from collections import OrderedDict

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP = os.environ.get("VVGO_APP", os.path.join(REPO_ROOT, "app.py"))
tree = ast.parse(io.open(APP, encoding='utf-8').read())

fn_pdf = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "process_pdf_request")
fn_res = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "_reserve_pdf_page_quota_if_needed")

STATE = {"released": [], "reserved": 0, "processed": [], "alerts": 0}
QUOTA = {"limit": 0}

def check_and_reserve_quotas(email, keys):
    if QUOTA["limit"] <= 0:
        return False, {k: (5, 5) for k in keys}, keys[0]
    QUOTA["limit"] -= 1
    STATE["reserved"] += 1
    return True, {k: (1, 5) for k in keys}, None

ns = {
    "OrderedDict": OrderedDict, "os": os,
    "MAX_PDF_PAGES": 200,
    "GEMINI_PRO_DEFAULT_LIMIT": 5,
    "GEMINI_GENERAL_ACCESS_PREFIX": "gemini_general_access",
    "_normalize_email_identity": lambda e: (e or "").lower() or None,
    "rate_limited_keys_in_request": lambda eng, llm: ["gemini-2.5-pro"],
    "quota_keys_for_request": lambda eng, llm, ocr_only=False, notebook_mode=False:
        ([] if (ocr_only or notebook_mode) and not eng else ["gemini-2.5-pro"]),
    "check_and_reserve_quotas": check_and_reserve_quotas,
    "release_quotas": lambda e, keys: STATE["released"].extend(keys),
    "_rate_limit_field_prefix": lambda k: "gemini_pro",
    "_send_general_access_cap_alert": lambda *a, **k: STATE.__setitem__("alerts", STATE["alerts"] + 1),
    "_send_rate_limit_hit_alert": lambda *a, **k: STATE.__setitem__("alerts", STATE["alerts"] + 1),
    "RATE_LIMIT_LABELS": {"gemini_pro": "Gemini Pro",
                          "gemini_general_access": "General Access"},
    "process_uploaded_file_with_resize": lambda f, max_pixels=None: f,
    "RESPONSE_HOST_NAME": "VoucherVisionGO",
    "resolve_payment_inference": lambda k=None, p=None: "x",
    # Inference marking is covered by tests_error_envelope.py; here the loop
    # only needs them to exist so control flow runs.
    "reset_inference_marker": lambda: None,
    "current_payment_inference": lambda request_scope=False: "not_processed",
    "_pdf_page_error": lambda filename, code, error, status_code, **kw: {
        "filename": filename, "error": error, "error_code": code,
        "status_code": status_code, **({"details": kw["details"]} if "details" in kw else {})},
}
# real resolver, so "both model params omitted" is exercised for PDFs too
_dm = next(n for n in tree.body if isinstance(n, ast.Assign) and getattr(n.targets[0],"id","")=="DEFAULT_MODEL")
_am = next(n for n in tree.body if isinstance(n, ast.Assign) and getattr(n.targets[0],"id","")=="API_TO_COST_MAPPING")
_rd = next(n for n in tree.body if getattr(n,"name",None)=="resolve_model_defaults")
exec(compile(ast.Module(body=[_dm,_am,_rd], type_ignores=[]), "<slice>", "exec"), ns)
exec(compile(ast.Module(body=[fn_res], type_ignores=[]), "<slice>", "exec"), ns)

class Page:
    def __init__(self, name): self.filename = name

class Proc:
    """Stub processor exposing only what process_pdf_request touches."""
    def __init__(self, fail_pages=()): self.fail_pages = set(fail_pages)
    def _log(self, *a, **k): pass
    def process_image_request(self, file=None, **kw):
        STATE["processed"].append(file.filename)
        if file.filename in self.fail_pages:
            return {"error": "boom"}, 500
        return OrderedDict([("ok", True)]), 200

def run(n_pages, quota, *, fail=(), api_key=None, vertex=None,
        engines=["gemini-2.5-pro"], llm="gemini-2.5-pro"):
    STATE.update(released=[], reserved=0, processed=[], alerts=0)
    QUOTA["limit"] = quota
    pages = [Page(f"p{i}.jpg") for i in range(1, n_pages + 1)]
    ns["convert_pdf_to_page_images"] = lambda b, f, dpi=150: pages
    exec(compile(ast.Module(body=[fn_pdf], type_ignores=[]), "<slice>", "exec"), ns)
    fn = ns["process_pdf_request"]
    file = types.SimpleNamespace(read=lambda: b"%PDF", filename="doc.pdf")
    res, status = fn(Proc(fail), file, caller_email="u@x.edu",
                     user_api_key=api_key, user_vertex_project=vertex,
                     engine_options=engines, llm_model_name=llm,
                     ocr_only=False, notebook_mode=False)
    return res, status

fails = 0
def check(label, cond, detail=""):
    global fails
    fails += not cond
    print(f"{'PASS' if cond else 'FAIL'}  {label:<52} {detail}")

# 1. Quota is metered per page (the bug: it was not metered at all).
r, _ = run(3, quota=10)
check("3-page PDF reserves 3 slots", STATE["reserved"] == 3, f"reserved={STATE['reserved']}")
check("all 3 pages processed", len(STATE["processed"]) == 3)

# 2. Exhaustion stops the run instead of processing for free.
r, _ = run(5, quota=2)
# 403, not 503: a lifetime cap will not reset with time.
errs = [p for p in r["pages"] if p.get("status_code") == 403]
check("cap at 2 -> only 2 pages processed", len(STATE["processed"]) == 2, f"processed={STATE['processed']}")
check("remaining 3 pages marked 403", len(errs) == 3, f"got {len(errs)}")
check("no extra Firestore txn per skipped page", STATE["reserved"] == 2, f"reserved={STATE['reserved']}")

# 3. A failed page returns its slot.
r, _ = run(3, quota=10, fail=("p2.jpg",))
check("failed page releases its reservation", STATE["released"] == ["gemini-2.5-pro"], f"released={STATE['released']}")
check("failure does not stop later pages", len(STATE["processed"]) == 3)

# 4. User-pays reserves nothing (both credential types).
r, _ = run(4, quota=0, api_key="AQ.key")
check("user gemini key -> no quota consumed", STATE["reserved"] == 0 and len(STATE["processed"]) == 4)
r, _ = run(4, quota=0, vertex="proj")
check("user vertex project -> no quota consumed", STATE["reserved"] == 0 and len(STATE["processed"]) == 4)

# 5. Envelope still well-formed.
r, _ = run(2, quota=10)
check("envelope keys intact", all(k in r for k in ("source_pdf","page_count","payment_inference","host","pages")))

# 5b. Pro/Restricted exhaustion during a PDF MUST alert (PDFs skip /process gate).
r, _ = run(3, quota=1)
check("non-general bucket exhaustion alerts from PDF path", STATE["alerts"] == 1, f"alerts={STATE['alerts']}")
msg = next(p["error"] for p in r["pages"] if p.get("status_code") == 403)
check("quota message names the category, not the model key",
      "Gemini Pro" in msg and "gemini-2.5-pro" not in msg, msg[:70])

# 6. THE BYPASS: a PDF with both model params omitted must still be metered.
r, _ = run(3, quota=10, engines=None, llm=None)
check("PDF w/ both model params omitted is metered", STATE["reserved"] == 3, f"reserved={STATE['reserved']}")
check("...and still processes its pages", len(STATE["processed"]) == 3)

print(f"\n{'ALL PASS' if not fails else str(fails)+' FAILED'}")
sys.exit(1 if fails else 0)

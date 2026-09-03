import os
import ast, io, re, sys, types

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = io.open(os.environ.get("VVGO_APP", os.path.join(REPO_ROOT, "app.py")), encoding='utf-8').read()
tree = ast.parse(SRC)
WANT = {"PAYMENT_AUTH_PARAM_ALIASES","PAYMENT_AUTH_HEADER_ALIASES","_BILLING_INTENT_NAMES",
        "_BILLING_INTENT_EXEMPT","_normalize_billing_param_name","_clean_optional_request_value",
        "_lookup_request_value","get_payment_auth_context","detect_unusable_billing_intent",
        "PAYMENT_INFERENCE_LABELS","RESPONSE_HOST_NAME","_auth_method_for","resolve_payment_inference"}
picked = []
for node in tree.body:
    name = getattr(node, "name", None)
    if name is None and isinstance(node, ast.Assign):
        t = node.targets[0]
        name = getattr(t, "id", None)
    if name in WANT:
        picked.append(node)
        WANT.discard(name)
assert not WANT, f"missing from app.py: {WANT}"

ns = {"re": re, "g": types.SimpleNamespace()}
exec(compile(ast.Module(body=picked, type_ignores=[]), "<app-slice>", "exec"), ns)
detect = ns["detect_unusable_billing_intent"]
resolve = ns["get_payment_auth_context"]
infer = ns["resolve_payment_inference"]
LABELS = ns["PAYMENT_INFERENCE_LABELS"]
HOST = ns["RESPONSE_HOST_NAME"]

class Headers(dict):
    def get(self, k, default=None):           # Werkzeug headers are case-insensitive
        for kk, vv in self.items():
            if kk.lower() == str(k).lower():
                return vv
        return default

class Req:
    def __init__(self, form=None, json=None, args=None, headers=None):
        self.form = form or {}
        self._json = json
        self.is_json = json is not None
        self.args = args or {}
        self.headers = Headers(headers or {})
    def get_json(self, silent=False):
        return self._json

GOOD = "AQ.Ab8RN6-realkey"
CASES = [
 ("no billing params (server mode)",              Req(form={"engines":"gemini-3.1-flash-lite"}),                     None, "server"),
 ("form gemini_api_key",                          Req(form={"gemini_api_key":GOOD}),                                 None, "user_gemini"),
 ("camelCase geminiApiKey",                       Req(form={"geminiApiKey":GOOD}),                                   None, "user_gemini"),
 ("NEW header X-Gemini-API-Key",                  Req(headers={"X-Gemini-API-Key":GOOD}),                            None, "user_gemini"),
 ("NEW header lowercase x-gemini-api-key",        Req(headers={"x-gemini-api-key":GOOD}),                            None, "user_gemini"),
 ("NEW header X-Vertex-Project + global region",  Req(headers={"X-Vertex-Project":"my-proj","X-Vertex-Region":"global"}), None, "user_vertex"),
 ("form vertex_project + global",                 Req(form={"vertex_project":"my-proj","vertex_region":"global"}),   None, "user_vertex"),
 ("vertex_region=global ALONE stays lenient",     Req(form={"vertex_region":"global"}),                              None, "server"),
 ("blank gemini_api_key -> 400",                  Req(form={"gemini_api_key":""}),                                    400, None),
 ("whitespace gemini_api_key -> 400",             Req(form={"gemini_api_key":"   "}),                                 400, None),
 ("blank header X-Gemini-API-Key -> 400",         Req(headers={"X-Gemini-API-Key":""}),                               400, None),
 ("typo 'gemini_key' -> 400",                     Req(form={"gemini_key":GOOD}),                                      400, None),
 ("typo header 'X-Gemini-Key' -> 400",            Req(headers={"X-Gemini-Key":GOOD}),                                 400, None),
 ("typo 'vertexProjectId' -> 400",                Req(form={"vertexProjectId":"my-proj"}),                            400, None),
 ("typo 'gcp_project' -> 400",                    Req(form={"gcp_project":"my-proj"}),                                400, None),
 ("VVGO X-API-Key never flagged",                 Req(headers={"X-API-Key":"OlNyl...","Authorization":"Bearer x","User-Agent":"curl/8"}), None, "server"),
 ("VVGO ?api_key= never flagged",                 Req(args={"api_key":"OlNyl..."}),                                   None, "server"),
 ("JSON body gemini_api_key",                     Req(json={"gemini_api_key":GOOD}),                                 None, "user_gemini"),
 ("JSON body typo -> 400",                        Req(json={"googleApiKey":GOOD}),                                    400, None),
]

fails = 0
for label, req, want_status, want_mode in CASES:
    payload, status = detect(req)
    got_mode = resolve(req)["auth_method"] if status is None else None
    ok = (status == want_status) and (got_mode == want_mode)
    fails += not ok
    detail = f"400 ({payload['parameter']})" if status else f"pass -> {got_mode}"
    print(f"{'PASS' if ok else 'FAIL'}  {label:<44} {detail}")
print()
LABEL_CASES = [
    (None,  None,      "VoucherVisionGO_credits"),
    (GOOD,  None,      "user_supplied_gemini_key"),
    (None,  "my-proj", "user_supplied_vertex_account"),
    (GOOD,  "my-proj", "user_supplied_vertex_account"),   # vertex wins, as in get_payment_auth_context
]
for key, proj, want in LABEL_CASES:
    got = infer(key, proj); ok = got == want; fails += not ok
    d = "key=%s project=%s" % ("Y" if key else "N", "Y" if proj else "N")
    print("%s  payment_inference %-22s -> %s" % ("PASS" if ok else "FAIL", d, got))

ok = set(LABELS) == {"server", "user_vertex", "user_gemini"}; fails += not ok
print("%s  labels cover every auth_method         -> %s" % ("PASS" if ok else "FAIL", sorted(LABELS.values())))
ok = HOST == "VoucherVisionGO"; fails += not ok
print("%s  host constant                          -> %s" % ("PASS" if ok else "FAIL", HOST))

n = 0
for label, req, want_status, want_mode in CASES:
    if want_status is not None:
        continue
    n += 1
    ctx = resolve(req)
    if infer(ctx["gemini_api_key"], ctx["vertex_project"]) != LABELS[ctx["auth_method"]]:
        fails += 1
        print("FAIL  label disagrees with auth_method: %s" % label)
print("PASS  label matches auth_method on all %d passing requests" % n)

total = len(CASES) + len(LABEL_CASES) + 3
print("")
print("%d/%d passed" % (total - fails, total))
sys.exit(1 if fails else 0)

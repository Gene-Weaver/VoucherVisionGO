"""Public processing routes and helpers emit the error envelope.

Static-analysis suite: walks app.py's AST to prove every error return in
/process, /process-url, /process-pdf-async and their helpers goes through the
envelope builders, that helpers keep their (dict, status) contracts, and that
this conversion stayed additive — no status or prose changed.

Run from the repository root:  python3 tests/tests_error_sites.py
"""
import ast
import io
import os
import re
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = io.open(os.environ.get("VVGO_APP", os.path.join(REPO_ROOT, "app.py")), encoding='utf-8').read()
tree = ast.parse(SRC)
lines = SRC.split('\n')

TARGET_ROUTES = {'/process', '/process-url', '/process-pdf-async'}
HELPERS = {'process_image_request', 'process_pdf_request', '_preflight_user_prompt',
           'detect_unusable_billing_intent'}

spans = []
for n in tree.body:
    if isinstance(n, ast.FunctionDef):
        for d in n.decorator_list:
            if isinstance(d, ast.Call) and getattr(d.func, 'attr', '') == 'route' \
               and d.args and d.args[0].value in TARGET_ROUTES:
                spans.append((n.lineno, n.end_lineno, f"route {d.args[0].value}", n))
for n in ast.walk(tree):
    if isinstance(n, ast.FunctionDef) and n.name in HELPERS:
        spans.append((n.lineno, n.end_lineno, f"helper {n.name}", n))


def owner(ln):
    best = None
    for a, b, label, node in spans:
        if a <= ln <= b and (best is None or (b - a) < (best[1] - best[0])):
            best = (a, b, label, node)
    return best


fails = 0
def check(label, cond, detail=""):
    global fails
    fails += not cond
    print(f"{'PASS' if cond else 'FAIL'}  {label:<62} {detail}")


print("=== every in-scope error return uses the envelope ===")
RAW = re.compile(r"(jsonify\(\s*\{\s*['\"]error|return \{'error'|return \(\{['\"]error|\{'error':)")
leftovers = []
for i, l in enumerate(lines, 1):
    if RAW.search(l) and owner(i):
        if re.search(r'\("(ocr_info|collage_info)",', l):
            continue          # nested field of a 200 result envelope, not an error body
        leftovers.append((i, owner(i)[2], l.strip()[:60]))
check("no hand-built error dict remains in scope", not leftovers,
      f"{len(leftovers)} left" if leftovers else "")
for r in leftovers:
    print(f"        app.py:{r[0]} [{r[1]}] {r[2]}")

print("\n=== helpers keep their (dict, status) contract ===")
for a, b, label, node in spans:
    if not label.startswith("helper"):
        continue
    bad = []
    for r in ast.walk(node):
        if not isinstance(r, ast.Return) or r.value is None:
            continue
        v = r.value
        if isinstance(v, ast.Tuple) and v.elts:
            v = v.elts[0]
        if isinstance(v, ast.Call) and getattr(v.func, 'id', '') == '_error_response':
            bad.append(r.lineno)
    check(f"{node.name} never returns a Flask response", not bad, str(bad))

print("\n=== routes use the response form, not the payload form ===")
for a, b, label, node in spans:
    if not label.startswith("route"):
        continue
    bad = [c.lineno for c in ast.walk(node)
           if isinstance(c, ast.Call) and getattr(c.func, 'id', '') == '_error_payload']
    check(f"{label} does not return a bare payload dict", not bad, str(bad))

print("\n=== every error_code used is in the closed taxonomy ===")
codes_node = next(n for n in tree.body if isinstance(n, ast.Assign)
                  and getattr(n.targets[0], 'id', '') == 'ERROR_CODES')
TAXONOMY = ast.literal_eval(ast.get_source_segment(SRC, codes_node.value)
                            .replace('frozenset(', '').rstrip(')'))
used = set()
for c in ast.walk(tree):
    if isinstance(c, ast.Call) and getattr(c.func, 'id', '') in ('_error_payload', '_error_response'):
        if c.args and isinstance(c.args[0], ast.Constant):
            used.add(c.args[0].value)
unknown = used - set(TAXONOMY)
check("no call site invents a code", not unknown, str(sorted(unknown)))
check("codes actually in use", len(used) >= 8, f"{len(used)} distinct: {sorted(used)}")

print("\n=== the conversion was additive: statuses unchanged ===")
# Statuses that must still appear on the converted call sites.
# Status Code Correction is complete, so these are the corrected values:
#   QUOTA_EXHAUSTED 503 -> 403 (a lifetime cap will not reset with time)
#   BAD_FILE_TYPE   400 -> 415 (unsupported media type, not a malformed request)
EXPECTED_STATUSES = {
    "SERVER_BUSY": {429}, "NO_FILE": {400}, "BAD_FILE_TYPE": {415},
    "UNAUTHENTICATED": {401}, "QUOTA_EXHAUSTED": {403},
    "VERTEX_NOT_LINKED": {403}, "VERTEX_PERMISSION_DENIED": {403},
    "MODEL_UNAVAILABLE": {404}, "PROMPT_NOT_FOUND": {404}, "FORBIDDEN": {403},
}
seen = {}
for c in ast.walk(tree):
    if isinstance(c, ast.Call) and getattr(c.func, 'id', '') in ('_error_payload', '_error_response'):
        if not (c.args and isinstance(c.args[0], ast.Constant)):
            continue
        code = c.args[0].value
        st = next((k.value for k in c.keywords if k.arg == 'status'), None)
        if isinstance(st, ast.Constant):
            seen.setdefault(code, set()).add(st.value)
        else:  # payload form: status is the tuple's second element
            parent_line = c.lineno
            for j in range(parent_line - 1, min(parent_line + 12, len(lines))):
                # Allow a trailing comment after the status, otherwise the
                # scan runs on and picks up an unrelated later call site.
                m = re.search(r"\),\s*(\d{3})\s*(?:#.*)?$", lines[j])
                if m:
                    seen.setdefault(code, set()).add(int(m.group(1)))
                    break
for code, expected in EXPECTED_STATUSES.items():
    got = seen.get(code, set())
    # `expected <= got` alone is not enough: an empty `got` (the code vanished
    # from app.py entirely) would satisfy a subset test, so require presence.
    check(f"{code} still returns {sorted(expected)}", bool(got) and expected <= got,
          f"got {sorted(got) if got else 'CODE ABSENT'}")

print("\n=== rate limit keeps its legacy fields for old clients ===")
rl = [c for c in ast.walk(tree)
      if isinstance(c, ast.Call) and getattr(c.func, 'id', '') == '_error_response'
      and c.args and getattr(c.args[0], 'value', None) == 'QUOTA_EXHAUSTED']
check("both rate-limit sites converted", len(rl) == 2, str(len(rl)))
for c in rl:
    legacy = next((k.value for k in c.keywords if k.arg == 'legacy'), None)
    keys = {k.value for k in legacy.keys} if isinstance(legacy, ast.Dict) else set()
    check(f"line {c.lineno}: legacy keeps gemini_pro_usage_* + model/count/limit",
          {"gemini_pro_usage_count", "gemini_pro_usage_limit",
           "model", "count", "limit"} <= keys, str(sorted(keys)))

print("\n=== status corrections are in place ===")
for code, want in (("QUOTA_EXHAUSTED", 403), ("BAD_FILE_TYPE", 415)):
    got = seen.get(code, set())
    check(f"{code} returns {want}", got == {want}, f"got {sorted(got)}")
check("no lifetime quota still answers 503",
      503 not in seen.get("QUOTA_EXHAUSTED", set()))

print("\n=== the dead Flask encoder is gone and key order is fixed ===")
check("app.json_encoder assignment removed (no-op since Flask 2.3)",
      "app.json_encoder = " not in SRC)
check("jsonify no longer alphabetizes error bodies", "app.json.sort_keys = False" in SRC)
check("success envelopes still use the explicit encoder",
      "cls=OrderedJsonEncoder" in SRC)

print("\n=== conversion was additive: prose unchanged vs. pre-conversion baseline ===")
import json


def norm(src):
    """Compare text only: strip the f-prefix, outer quotes, and whitespace."""
    t = re.sub(r"\s+", " ", (src or "").strip())
    return re.sub(r"""^f["']|["']$""", "", t)


BASE = json.load(io.open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                      "error_prose_baseline.json"), encoding="utf-8"))

# _error_payload(code, error, ...) / _error_response(code, error, ...)
# _pdf_page_error(filename, code, error, status_code, ...)
PROSE_ARG_INDEX = {'_error_payload': 1, '_error_response': 1, '_pdf_page_error': 2}

# Baseline entries deliberately no longer emitted, each with a justification.
ALLOWED_REMOVALS = {
    # SANITIZATION (OPEN_CORRECTIONS #1, closed): raw exception text is no
    # longer returned to callers. Each of these is replaced by a fixed,
    # actionable message; the exception goes to the log under the request ID.
    "Failed to convert PDF: {str(e)}":
        "SANITIZED: replaced by a fixed message; the exception is logged",
    "Image resize failed: {str(e)}":
        "SANITIZED: replaced by a fixed per-page message; the exception is logged",
    "Error processing image: {str(e)}":
        "SANITIZED: replaced by a fixed 400 message; the exception is logged",
    "str(e)":
        "SANITIZED (x2): the two generic provider paths now go through "
        "classify_provider_failure(), which returns a fixed message and logs "
        "the raw exception under the request ID",
    "Failed to fetch URL: {str(last_exception)}":
        "the /process-url success-shaped HTTP 200 envelope was replaced by a "
        "classified top-level error; this nested ocr_info field no longer "
        "exists (OPEN_CORRECTIONS #2, closed)",
    "Image could not be retrieved from URL.":
        "nested collage_info field of the same removed envelope "
        "(OPEN_CORRECTIONS #2, closed)",
    "An unexpected server error occurred: {str(e)}":
        "SANITIZED: the in-loop URL failure no longer returns raw exception "
        "text; classify_fetch_failure() supplies a fixed message and the raw "
        "exception is logged against the request ID (OPEN_CORRECTIONS #1)",
    "result.get('error', 'Unknown error')":
        "a failed PDF page now carries the inner envelope through verbatim "
        "instead of re-extracting its message, so this expression is gone by "
        "design (see _pdf_page_error and the page-failure branch)",
}

found = {"error": {"literal": {}, "template": {}, "expr": {}},
         "message": {"literal": {}, "template": {}, "expr": {}}}


def record(field, node):
    b = found[field]
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        b["literal"][node.value] = b["literal"].get(node.value, 0) + 1
    elif isinstance(node, ast.JoinedStr):
        t = norm(ast.get_source_segment(SRC, node))
        b["template"][t] = b["template"].get(t, 0) + 1
    else:
        e = norm(ast.get_source_segment(SRC, node))
        b["expr"][e] = b["expr"].get(e, 0) + 1


for c in ast.walk(tree):
    # Only in-scope call sites count. The builders call each other internally
    # (_error_response -> _error_payload, _pdf_page_error -> _error_payload);
    # those are plumbing, not public prose.
    if isinstance(c, ast.Call) and getattr(c.func, 'id', '') in PROSE_ARG_INDEX:
        if not owner(c.lineno):
            continue
        i = PROSE_ARG_INDEX[c.func.id]
        for a in c.args[i:i + 1]:
            record("error", a)
        # `message` is baselined separately and never counted as `error`
        # prose: moving text out of error into message must fail the check,
        # not satisfy it.
        for k in c.keywords:
            if k.arg == 'message':
                record("message", k.value)
    elif isinstance(c, ast.Dict) and owner(getattr(c, 'lineno', 0)):
        for k, v in zip(c.keys, c.values):
            if isinstance(k, ast.Constant) and k.value in ("error", "message"):
                record(k.value, v)

for removed, why in ALLOWED_REMOVALS.items():
    print(f"      note: {removed!r} intentionally removed \u2014 {why}")

for field in ("error", "message"):
    for kind in ("literal", "template", "expr"):
        base = BASE[field][kind]
        if not base:
            continue
        got = found[field][kind]
        missing = sorted(f"{b!r} (x{n}, found {got.get(b, 0)})"
                         for b, n in base.items()
                         if got.get(b, 0) < n and b not in ALLOWED_REMOVALS)
        check(f"all {len(base)} baseline `{field}` {kind}s still emitted",
              not missing, "; ".join(missing)[:110] if missing else "")

print("\n=== nested PDF page failures carry the envelope ===")
pdf = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)
           and n.name == "process_pdf_request")
bare = []
for c in ast.walk(pdf):
    if isinstance(c, ast.Call) and getattr(c.func, 'attr', '') == 'append' and c.args:
        a = c.args[0]
        if isinstance(a, ast.Dict):
            keys = {k.value for k in a.keys if isinstance(k, ast.Constant)}
            if 'error' in keys and 'error_code' not in keys:
                bare.append(c.lineno)
check("no bare {filename,error,status_code} page entry remains", not bare, str(bare))
helper_calls = [c.lineno for c in ast.walk(pdf) if isinstance(c, ast.Call)
                and getattr(c.func, 'id', '') == '_pdf_page_error']
check("page failures go through _pdf_page_error", len(helper_calls) >= 3, str(len(helper_calls)))

print("\n=== payment_inference is gated in EVERY response shape ===")
ungated = []
for c in ast.walk(tree):
    if isinstance(c, ast.Call) and getattr(c.func, 'id', '') == 'resolve_payment_inference':
        fn = owner(c.lineno)
        if fn:
            ungated.append((c.lineno, fn[2]))
check("no result envelope calls resolve_payment_inference directly", not ungated, str(ungated))
gated = [c.lineno for c in ast.walk(tree) if isinstance(c, ast.Call)
         and getattr(c.func, 'id', '') == 'current_payment_inference']
# Four remain: three in process_image_request, one in the PDF wrapper. The
# fifth was the /process-url success-shaped envelope, now a classified error.
check("every result envelope uses current_payment_inference", len(gated) >= 4, str(len(gated)))
resets = [c.lineno for c in ast.walk(pdf) if isinstance(c, ast.Call)
          and getattr(c.func, 'id', '') == 'reset_inference_marker']
check("PDF loop resets the marker per page", len(resets) == 1, str(resets))

print(f"\n{'ALL PASS' if not fails else str(fails) + ' FAILED'}")
sys.exit(1 if fails else 0)

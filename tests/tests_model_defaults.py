"""resolve_model_defaults + the quota keys it produces, from the real app.py."""
import os
import ast, io, re, sys

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

# Take the whole quota-registry region (it mixes AnnAssign, Assign-to-subscript
# and a for-loop), plus the two functions defined elsewhere.
names = [top_name(n) for n in tree.body]
start = names.index("GEMINI_PRO_DEFAULT_LIMIT")
end = names.index("_rate_limit_field_prefix")
body = tree.body[start:end + 1]
body += [n for n in tree.body if top_name(n) in ("rate_limited_keys_in_request", "quota_keys_for_request")]
have = {top_name(n) for n in body}
for req in ("DEFAULT_MODEL", "API_TO_COST_MAPPING", "resolve_model_defaults",
            "RATE_LIMIT_LABELS", "rate_limited_keys_in_request", "quota_keys_for_request"):
    assert req in have, f"missing {req} from extracted region"

ns={"re":re}
exec(compile(ast.Module(body=body,type_ignores=[]),"<slice>","exec"), ns)

resolve=ns["resolve_model_defaults"]; keys=ns["rate_limited_keys_in_request"]
qkeys=ns["quota_keys_for_request"]
prefix=ns["_rate_limit_field_prefix"]; LABELS=ns["RATE_LIMIT_LABELS"]
DEFAULT=ns["DEFAULT_MODEL"]

fails=0
def check(label, cond, detail=""):
    global fails; fails += not cond
    print(f"{'PASS' if cond else 'FAIL'}  {label:<58} {detail}")

print("=== THE BYPASS: both model params omitted ===")
raw = keys(None, None)
check("BEFORE fix: raw keys for (None, None) are empty", raw == [], f"{raw}")
eng, llm = resolve(None, None)
after = keys(eng, llm)
check("AFTER fix: defaults applied -> quota key produced", len(after) == 1, f"{eng}/{llm} -> {after}")
check("default model is gemini-3.1-flash-lite", eng == [DEFAULT] and llm == DEFAULT and DEFAULT == "gemini-3.1-flash-lite", DEFAULT)
check("default lands in General Access bucket",
      prefix(after[0]) == ns["GEMINI_GENERAL_ACCESS_PREFIX"], LABELS.get(prefix(after[0])))
check("default is priced (has a cost constant)", DEFAULT in ns["API_TO_COST_MAPPING"])

print("\n=== omission variants ===")
for label, eo, lm, ocr, nb in [
    ("engines omitted only",        None,               "gemini-2.5-pro", False, False),
    ("llm_model omitted only",      ["gemini-2.5-pro"], None,             False, False),
    ("empty-string llm_model",      None,               "   ",            False, False),
    ("empty list engines",          [],                 None,             False, False),
    ("list of blanks engines",      ["", "  "],         None,             False, False),
    ("ocr_only, both omitted",      None,               None,             True,  False),
    ("notebook_mode, both omitted", None,               None,             False, True),
]:
    e,l = resolve(eo, lm, ocr_only=ocr, notebook_mode=nb)
    k = keys(e,l)
    check(label, len(k) >= 1, f"{e}/{l} -> {[LABELS.get(prefix(x),x) for x in k]}")

print("\n=== ocr_only must not pull in a second bucket ===")
e,l = resolve(["gemini-2.5-pro"], None, ocr_only=True)
k = qkeys(e,l,ocr_only=True)
check("ocr_only w/ pro engine charges Pro only, not Pro+General", len(k) == 1 and prefix(k[0]) == "gemini_pro",
      f"{l} -> {[LABELS.get(prefix(x),x) for x in k]}")
e,l = resolve(["gemini-2.5-pro"], None, ocr_only=False)
k = qkeys(e,l)
check("full pipeline w/ pro engine charges Pro AND default's bucket", len(k) == 2,
      f"{l} -> {[LABELS.get(prefix(x),x) for x in k]}")

print("\n=== OCR-only must not charge for a parsing call it never makes ===")
# The webpage sends engines + llm_model + ocr_only together on every request
# (webpage/js/vouchervisiongo.js). Only the OCR engine's bucket may be charged.
e, l = resolve(["gemini-3.1-pro"], "gemini-3.1-flash-lite", ocr_only=True)
k = qkeys(e, l, ocr_only=True)
check("ocr_only + explicit pro engine + explicit flash-lite llm",
      len(k) == 1 and prefix(k[0]) == "gemini_pro",
      f"{e}/{l} -> {[LABELS.get(prefix(x), x) for x in k]}")
check("...and the caller's model choice is NOT rewritten",
      e == ["gemini-3.1-pro"] and l == "gemini-3.1-flash-lite", f"{e}/{l}")
k = qkeys(e, l, notebook_mode=True)
check("same for notebook_mode", len(k) == 1 and prefix(k[0]) == "gemini_pro",
      f"{[LABELS.get(prefix(x), x) for x in k]}")
k = qkeys(e, l)
check("full pipeline DOES charge both (parsing really runs)", len(k) == 2,
      f"{[LABELS.get(prefix(x), x) for x in k]}")
e, l = resolve(None, None, ocr_only=True)
check("ocr_only w/ everything omitted still metered", len(qkeys(e, l, ocr_only=True)) == 1,
      f"{e}/{l}")

print("\n=== explicit values are never overridden ===")
e,l = resolve(["gemini-3.5-flash"], "gemini-3.1-pro-preview")
check("caller-specified models pass through", e == ["gemini-3.5-flash"] and l == "gemini-3.1-pro-preview", f"{e}/{l}")

print(f"\n{'ALL PASS' if not fails else str(fails)+' FAILED'}")
sys.exit(1 if fails else 0)

"""Source-image fetch failures map to the right code, status and message.

Extracts classify_fetch_failure / TerminalFetchError / _exception_chain from
app.py and drives them with real exception objects, including chained causes.

Run from the repository root:  python3 tests/tests_fetch_classification.py
"""
import ast
import io
import re
import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = io.open(os.environ.get("VVGO_APP", os.path.join(REPO_ROOT, "app.py")), encoding='utf-8').read()
tree = ast.parse(SRC)


def top_name(n):
    if isinstance(n, (ast.FunctionDef, ast.ClassDef)):
        return n.name
    if isinstance(n, ast.Assign):
        return getattr(n.targets[0], "id", None)
    return None


WANT = ["TerminalFetchError", "URL_INVALID_EXCEPTIONS", "_exception_chain",
        "classify_fetch_failure", "classify_provider_failure",
        "validate_image_url", "check_url_destination",
        "URL_FETCH_MAX_REDIRECTS", "URL_FETCH_READ_TIMEOUT",
        "TERMINAL_FETCH_FAILURES"]
body = [n for n in tree.body if top_name(n) in WANT]
assert {top_name(n) for n in body} == set(WANT), "missing from app.py"
import ipaddress
import socket
from urllib.parse import urlparse
sys.path.insert(0, REPO_ROOT)
from guarded_fetch import (  # noqa: E402
    BlockedDestination, FetchDeadlineExceeded, InvalidFetchUrl,
    address_is_public, resolve_public_addresses, validate_url_shape,
)
ns = {"urlparse": urlparse, "ipaddress": ipaddress, "socket": socket,
      "SSRF_ALLOWED_PORTS": __import__("guarded_fetch").ALLOWED_PORTS,
      "BlockedDestination": BlockedDestination,
      "FetchDeadlineExceeded": FetchDeadlineExceeded, "InvalidFetchUrl": InvalidFetchUrl,
      "address_is_public": address_is_public,
      "resolve_public_addresses": resolve_public_addresses,
      "validate_url_shape": validate_url_shape}
exec(compile(ast.Module(body=body, type_ignores=[]), "<app-slice>", "exec"), ns)
classify = ns["classify_fetch_failure"]
Terminal = ns["TerminalFetchError"]
validate = ns["validate_image_url"]
destination = ns["check_url_destination"]
is_public = address_is_public

fails = 0
def check(label, cond, detail=""):
    global fails
    fails += not cond
    print(f"{'PASS' if cond else 'FAIL'}  {label:<58} {detail}")


def make(name, base=Exception):
    return type(name, (base,), {})


def chained(outer, inner):
    """`raise outer from inner`, without unwinding."""
    try:
        try:
            raise inner
        except Exception as i:
            raise outer from i
    except Exception as e:
        return e


print("=== each failure mode gets its own status ===")
CASES = [
    ("connect timeout",        make("ConnectTimeout")(),      'UPSTREAM_TIMEOUT', 504),
    ("read timeout",           make("ReadTimeout")(),         'UPSTREAM_TIMEOUT', 504),
    # A bare PermissionError is NOT a blocked host: only the allowlist
    # rejection means URL_BLOCKED, and it arrives as a TerminalFetchError.
    ("filesystem permission",  PermissionError("not allowed"), 'INTERNAL_ERROR',  500),
    ("malformed URL",          make("InvalidURL")(),          'URL_INVALID',     400),
    ("unsupported scheme",     make("UnsupportedProtocol")(), 'URL_INVALID',     400),
    ("connect error",          make("ConnectError")(),        'FETCH_FAILED',    502),
    ("remote HTTP error",      make("HTTPStatusError")(),     'FETCH_FAILED',    502),
    ("not an image",           make("UnidentifiedImageError")(), 'INVALID_INPUT', 415),
    ("anything else",          ValueError("???"),             'INTERNAL_ERROR',  500),
]
for label, exc, want_code, want_status in CASES:
    code, status, msg = classify(exc)
    check(f"{label} -> {want_code} {want_status}",
          (code, status) == (want_code, want_status), f"got {code} {status}")

print("\n=== the most specific cause wins through the chain ===")
# smart_fetch raises RuntimeError *from* the real httpx reason.
e = chained(RuntimeError("Failed to fetch image after 3 attempts"), make("ReadTimeout")())
code, status, _ = classify(e)
check("RuntimeError raised from a timeout -> 504, not 502",
      (code, status) == ('UPSTREAM_TIMEOUT', 504), f"got {code} {status}")
e = chained(RuntimeError("Failed after retries"), make("ConnectError")())
check("RuntimeError raised from a connect error -> 502",
      classify(e)[1] == 502, str(classify(e)[1]))
# fallback failure chained from the smart_fetch failure
e = chained(make("ConnectError")(), make("ReadTimeout")())
check("fallback error chained from a timeout keeps the timeout",
      classify(e)[1] == 504, str(classify(e)[1]))
e = chained(RuntimeError("outer"), chained(RuntimeError("mid"), make("ConnectTimeout")()))
check("deeply nested cause still resolves", classify(e)[1] == 504, str(classify(e)[1]))

print("\n=== terminal failures are terminal ===")
t = Terminal('URL_BLOCKED', "host not permitted", 403, cause=PermissionError("x"))
code, status, msg = classify(t)
check("TerminalFetchError classifies to itself", (code, status) == ('URL_BLOCKED', 403))
check("TerminalFetchError keeps its message", msg == "host not permitted", msg)

fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)
          and n.name == "process_image_by_url")
src = ast.get_source_segment(SRC, fn)
# NOTE: the route deliberately uses the original anti_bot_fetch downloader
# with its bare `except:` fallback to process_url_image_with_resize. The
# pre-flight destination check below is what protects that path.
check("the pre-flight check runs before any fetch attempt",
      src.index("check_url_destination(image_url") < src.index("smart_fetch_image"))
check("both downloaders sit behind that one check",
      "smart_fetch_image_as_filestorage(" in src
      and "process_url_image_with_resize(" in src)


print("\n=== no raw exception text reaches the caller ===")
for label, exc, _, _ in CASES:
    _, _, msg = classify(exc)
    check(f"{label}: message is a fixed sentence",
          "Traceback" not in msg and str(exc) not in msg or not str(exc),
          msg[:46])

print("\n=== /process-url no longer answers a dead URL with HTTP 200 ===")
check("success-shaped failure envelope is gone", "error_response_data" not in SRC)

# Isolate the "all attempts failed" branch and assert on the branch itself,
# not on the whole function: the classify() call sits on a different line from
# the return, so grepping the function would still pass if the return were
# changed back to a 200.
branch = next(n for n in ast.walk(fn)
              if isinstance(n, ast.If)
              and "last_exception is not None" in (ast.get_source_segment(SRC, n.test) or ""))
bsrc = ast.get_source_segment(SRC, branch)
returns = [r for r in ast.walk(branch) if isinstance(r, ast.Return)]
check("failure branch has exactly one return", len(returns) == 1, str(len(returns)))
rsrc = ast.get_source_segment(SRC, returns[0]) if returns else ""
check("...and it is an _error_response", rsrc.startswith("return _error_response("), rsrc[:44])
check("...carrying the classified status, not a literal",
      "status=status" in rsrc, rsrc[:60])
# AST, not text: a comment mentioning 200 must not trip this, and a literal
# 200 status must.
literal_200 = [n.lineno for n in ast.walk(branch)
               if isinstance(n, ast.Constant) and n.value == 200]
check("...and no literal 200 status in the branch", not literal_200, str(literal_200))
check("branch classifies before returning",
      "classify_fetch_failure(last_exception)" in bsrc)
check("...and still releases the reserved quota",
      "release_quotas(user_email, reserved_keys)" in bsrc)

print("\n=== WRAPPED causes: smart_fetch wraps everything in RuntimeError ===")
# The bug this covers: RuntimeError was tested before image errors, so a
# wrapped unreadable image reported 502 instead of 415.
WRAPPED = [
    ("unreadable image",  make("UnidentifiedImageError")(), 'INVALID_INPUT',    415),
    ("decompression bomb", make("DecompressionBombError")(), 'INVALID_INPUT',   415),
    ("read timeout",      make("ReadTimeout")(),            'UPSTREAM_TIMEOUT', 504),
    ("malformed URL",     make("InvalidURL")(),             'URL_INVALID',      400),
    ("connect error",     make("ConnectError")(),           'FETCH_FAILED',     502),
]
for label, inner, want_code, want_status in WRAPPED:
    direct = classify(inner)
    wrapped = classify(chained(RuntimeError("Failed to fetch image after 2 attempts"), inner))
    check(f"wrapped {label} -> {want_code} {want_status}",
          wrapped[:2] == (want_code, want_status), f"got {wrapped[0]} {wrapped[1]}")
    check(f"...and matches the direct classification",
          wrapped[:2] == direct[:2], f"direct={direct[:2]} wrapped={wrapped[:2]}")
# A bare RuntimeError with nothing recognizable inside is still a fetch failure.
check("bare RuntimeError -> 502", classify(RuntimeError("x"))[:2] == ('FETCH_FAILED', 502))

print("\n=== PermissionError alone must NOT mean URL_BLOCKED ===")
# Only the allowlist rejection means blocked, and that arrives as a
# TerminalFetchError. A filesystem permission fault is a server problem.
code, status, _ = classify(PermissionError("cannot write /tmp/x"))
check("bare PermissionError is not 403", status != 403, f"got {code} {status}")
check("bare PermissionError -> 500 INTERNAL_ERROR", (code, status) == ('INTERNAL_ERROR', 500),
      f"got {code} {status}")
code, status, _ = classify(chained(RuntimeError("wrapped"), PermissionError("fs denied")))
check("PermissionError wrapped in RuntimeError is not 403", status != 403, f"got {code} {status}")
check("...it is a fetch failure, not a blocked host", (code, status) == ('FETCH_FAILED', 502),
      f"got {code} {status}")
check("only TerminalFetchError yields URL_BLOCKED",
      classify(Terminal('URL_BLOCKED', "nope", 403))[:2] == ('URL_BLOCKED', 403))

print("\n=== malformed URLs are terminal, and never look like a blocked host ===")
for url, why in [("", "empty"), ("not a url", "no scheme"), ("ftp://h/x.jpg", "wrong scheme"),
                 ("https:///x.jpg", "no host"), ("javascript:alert(1)", "non-http scheme")]:
    e = validate(url)
    check(f"{why:<16} -> terminal 400 URL_INVALID",
          e is not None and (e.error_code, e.status) == ('URL_INVALID', 400),
          f"{url!r} -> {None if e is None else (e.error_code, e.status)}")
check("a valid URL passes validation", validate("https://a.example.com/x.jpg") is None)
# The reported interaction: with an allowlist configured, a hostless URL used
# to be tested against the allowlist and reported 403 rather than 400.
e = validate("https:///x.jpg")
check("a hostless URL is 400, not 403",
      (e.error_code, e.status) == ('URL_INVALID', 400), f"{(e.error_code, e.status)}")
check("the destination check runs before any fetch",
      SRC.index("check_url_destination(image_url")
      < SRC.index("smart_fetch_image_as_filestorage("))
check("both downloaders share one redirect validator",
      "destination_check=validate_redirect_target" in SRC
      and "validate_redirect_target(current_url)" in SRC)
check("the route's check is the full one, not shape-only",
      "url_error = validate_image_url(image_url)" not in SRC)

print("\n=== there is no host allowlist ===")
# Removed at the maintainer's direction: VoucherVisionGO fetches from
# arbitrary institutional portals, so the public-address rule is the boundary.
for src_name in ("app.py", "guarded_fetch.py", "anti_bot_fetch.py"):
    src_text = io.open(os.path.join(REPO_ROOT, src_name), encoding="utf-8").read()
    check(f"{src_name:<20} reads no ALLOWED_IMAGE_DOMAINS",
          "ALLOWED_IMAGE_DOMAINS" not in src_text)
    check(f"{src_name:<20} has no allowed_domains plumbing",
          "allowed_domains" not in src_text)

print("\n=== SSRF: legitimate herbarium URLs still work ===")
for url in ["https://swbiodiversity.org/imglib/seinet/KHD/KHD00041592_lg.jpg",
            "https://example.com/a.jpg"]:
    check(f"allowed: {url[:44]}", destination(url) is None)


print("\n=== SSRF: guards live in one place ===")
check("route delegates to guarded_fetch, not a local copy",
      "from guarded_fetch import" in SRC)
check("the route's check is the full destination check, not shape-only",
      "check_url_destination(image_url" in SRC)
check("the pre-flight check short-circuits before any fetch",
      SRC.index("url_error = check_url_destination(image_url")
      < SRC.index("smart_fetch_image_as_filestorage("))
check("no chained alternative-attempt exceptions remain",
      "from smart_fetch_error" not in SRC)

print("\n=== the anti-bot downloader is repaired and guarded ===")
ABF_PATH = os.path.join(REPO_ROOT, "anti_bot_fetch.py")
check("anti_bot_fetch.py is present", os.path.exists(ABF_PATH))
ABF_SRC = io.open(ABF_PATH, encoding="utf-8").read()
check("app.py imports it", "from anti_bot_fetch import smart_fetch_image_as_filestorage" in SRC)
# The keyword-only form raises ValueError before the retry loop, which is why
# this downloader never ran and every request used the requests fallback.
check("httpx.Timeout uses the positional-default form",
      "httpx.Timeout(read_timeout, connect=connect_timeout)" in ABF_SRC)
check("...so no Timeout construction is keyword-only",
      "httpx.Timeout(connect=" not in ABF_SRC)
# Now that it actually runs, its redirects have to be validated.
check("redirects are not auto-followed", "follow_redirects=False" in ABF_SRC
      and "follow_redirects=True" not in ABF_SRC)
check("every redirect hop is validated", "_open_validated(" in ABF_SRC)
check("...by calling the shared validator, which raises its own verdict",
      "destination_check(nxt)" in ABF_SRC and "destination_check(url)" in ABF_SRC)
check("the route supplies the shared redirect validator",
      "destination_check=validate_redirect_target" in SRC)
check("...and the terminal exception tuple, so verdicts escape the retry loop",
      "terminal_exceptions=TERMINAL_FETCH_FAILURES" in SRC
      and "except terminal_exceptions:" in ABF_SRC)
check("the fallback uses that same validator on every hop",
      "validate_redirect_target(current_url)" in SRC)
check("...so a destination refused by one path cannot be fetched by the other",
      SRC.count("def validate_redirect_target") == 1)
check("both clients are context-managed",
      "with httpx.Client(" in ABF_SRC and "with requests.Session() as session:" in SRC)
check("bodies are streamed into a spooled temp file, not buffered whole",
      "SpooledTemporaryFile(" in ABF_SRC and "SpooledTemporaryFile(" in SRC)
# AST, not substring: a comment explaining why the cookie is not passed must
# not satisfy this, and a real `cookie=` argument must break it.
_smart_calls = [c for c in ast.walk(tree) if isinstance(c, ast.Call)
                and getattr(c.func, "id", "") == "smart_fetch_image_as_filestorage"]
check("the route calls the downloader once", len(_smart_calls) == 1, str(len(_smart_calls)))
check("PORTAL_COOKIE is not sent to caller-supplied hosts",
      all(not any(k.arg == "cookie" for k in c.keywords) for c in _smart_calls))
check("http2 support is declared as a dependency",
      "httpx[http2]" in io.open(os.path.join(REPO_ROOT, "requirements.txt"), "rb")
      .read().decode("utf-16" if open(os.path.join(REPO_ROOT, "requirements.txt"), "rb")
                     .read(2) in (b"\xff\xfe", b"\xfe\xff") else "utf-8"))
check("guarded_fetch holds only the URL guards, no downloader",
      "def guarded_stream" not in io.open(os.path.join(REPO_ROOT, "guarded_fetch.py"),
                                          encoding="utf-8").read())

print(f"\n{'ALL PASS' if not fails else str(fails) + ' FAILED'}")
sys.exit(1 if fails else 0)

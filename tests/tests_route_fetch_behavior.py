"""Route-level behaviour of the image fetch path.

Drives the real process_image_by_url() with the REAL
smart_fetch_image_as_filestorage() as the primary downloader and the REAL
process_url_image_with_resize() as its fallback. Nothing between the route and
the network is stubbed: httpx and requests are mocked at the transport layer
only.

This matters because an earlier version of this suite substituted its own
smart() function, which hid the fact that the downloader was swallowing
terminal exceptions, retrying them, and handing them to the fallback.

Needs httpx/Pillow:  ./.venv_cors/bin/python tests/tests_route_fetch_behavior.py
"""
import ast
import io
import os
import sys
import types

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

import httpx  # noqa: E402
from PIL import Image  # noqa: E402

import anti_bot_fetch  # noqa: E402
from anti_bot_fetch import smart_fetch_image_as_filestorage  # noqa: E402
from guarded_fetch import (  # noqa: E402
    BlockedDestination, FetchDeadlineExceeded, InvalidFetchUrl,
    address_is_public, resolve_public_addresses, validate_url_shape,
)

SRC = io.open(os.environ.get("VVGO_APP", os.path.join(REPO_ROOT, "app.py")),
              encoding="utf-8").read()
tree = ast.parse(SRC)


def top(n):
    if isinstance(n, (ast.FunctionDef, ast.ClassDef)):
        return n.name
    if isinstance(n, ast.Assign):
        return getattr(n.targets[0], "id", None)
    return None


REAL = ["TerminalFetchError", "TERMINAL_FETCH_FAILURES", "_exception_chain",
        "URL_INVALID_EXCEPTIONS", "classify_fetch_failure", "classify_provider_failure",
        "check_url_destination", "validate_redirect_target", "validate_image_url", "process_url_image_with_resize",
        "URL_FETCH_MAX_REDIRECTS", "URL_FETCH_READ_TIMEOUT",
        "SPOOL_MAX_IN_MEMORY_BYTES",
        "process_image_by_url"]
picked = [n for n in tree.body if top(n) in REAL]

fails = 0


def check(label, cond, detail=""):
    global fails
    fails += not cond
    print(f"{'PASS' if cond else 'FAIL'}  {label:<58} {detail}")


missing = set(REAL) - {top(n) for n in picked}
check("every route symbol exists in app.py", not missing, str(sorted(missing)))
for n in picked:
    if isinstance(n, ast.FunctionDef):
        n.decorator_list = []

PUBLIC = ["93.184.216.34"]
PRIVATE = ["10.0.0.5"]
RESOLVES = {"portal.test": PUBLIC, "other.test": PUBLIC, "rebind.test": PRIVATE}


def fake_dns(host):
    """DNS only. Hosts under .invalid deliberately do not resolve."""
    if host.endswith(".invalid") or host not in RESOLVES:
        raise OSError(f"no such host: {host}")
    return RESOLVES[host]
STATE = {}


def png(size=(20, 15)):
    buf = io.BytesIO()
    Image.new("RGB", size, (10, 120, 200)).save(buf, format="PNG")
    return buf.getvalue()


class Hdr(dict):
    def add(self, k, v): self[k] = v
    def get(self, k, d=None): return dict.get(self, k, d)


class Resp:
    def __init__(self, body, status=200):
        self.body, self.status_code, self.headers = body, status, Hdr()


class Req:
    is_json = False
    method = "POST"
    args, headers, files, cookies = {}, Hdr(), {}, {}

    def __init__(self, url):
        self.form = {"image_url": url}

    def get_json(self, silent=False):
        return None


class FakeRequestsResponse:
    """Stands in for a `requests` response, driven by a handler."""

    def __init__(self, status=200, headers=None, body=b""):
        self.status_code = status
        self.headers = headers or {}
        self._body = body
        self.text = ""
        self.request = types.SimpleNamespace(headers={})
        self.closed = False

        self.closed = False

    def raise_for_status(self):
        if self.status_code >= 400:
            raise IOError(f"HTTP {self.status_code}")

    def iter_content(self, chunk_size=None):
        yield self._body

    def close(self):
        self.closed = True


def make_session(handler, log):
    class FakeSession:
        def __init__(self):
            self.headers = {}
            self.cookies = {}

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            self.closed = True
            return False

        def get(self, url, **kwargs):
            log.append(("requests", url, dict(self.cookies)))
            resp = handler(url, dict(self.cookies))
            for k, v in (resp.headers.get("_set_cookie") or {}).items():
                self.cookies[k] = v
            return resp
    return FakeSession


def build_route(url, requests_handler, httpx_handler=None):
    """Exec the real route with BOTH real downloaders; only HTTP is mocked."""
    log = []
    STATE.clear()

    real_httpx_client = httpx.Client

    def mock_httpx_client(**kwargs):
        def handler(request):
            log.append(("smart", str(request.url), None))
            return (httpx_handler or (lambda u: httpx.Response(599)))(str(request.url))
        return real_httpx_client(transport=httpx.MockTransport(handler),
                                 headers=kwargs.get("headers"),
                                 follow_redirects=False)

    def smart(u, **kwargs):
        # The REAL function. Only its HTTP client is swapped.
        httpx.Client = mock_httpx_client
        try:
            return smart_fetch_image_as_filestorage(u, **kwargs)
        finally:
            httpx.Client = real_httpx_client

    ns = {
        "os": os, "io": io, "tempfile": __import__("tempfile"), "time": types.SimpleNamespace(sleep=lambda s: None),
        "json": __import__("json"), "uuid": __import__("uuid"),
        "urlparse": __import__("urllib.parse", fromlist=["urlparse"]).urlparse,
        "urljoin": __import__("urllib.parse", fromlist=["urljoin"]).urljoin,
        "request": Req(url), "jsonify": lambda p: p,
        "make_response": lambda b, st=200: Resp(b, st),
        "logger": types.SimpleNamespace(**{k: (lambda *a, **kw: None) for k in
                                           ("info", "error", "warning", "exception", "debug")}),
        "requests": types.SimpleNamespace(
            Session=make_session(requests_handler, log),
            exceptions=types.SimpleNamespace(RequestException=IOError)),
        "smart_fetch_image_as_filestorage": smart,
        "APP_USER_AGENT": "test/1.0",
        "BlockedDestination": BlockedDestination,
        "InvalidFetchUrl": InvalidFetchUrl, "FetchDeadlineExceeded": FetchDeadlineExceeded,
        "validate_url_shape": validate_url_shape,
        "address_is_public": address_is_public,
        "resolve_public_addresses": lambda h, resolver=None:
            resolve_public_addresses(h, resolver=fake_dns),
        "Image": Image,
        "FileStorage": __import__("werkzeug.datastructures",
                                  fromlist=["FileStorage"]).FileStorage,
        "resize_image_to_max_pixels": lambda im, mp: im,
        "extract_filename_from_url": lambda u: "x.jpg",
        "get_user_email_from_request": lambda r: "u@x.edu",
        "get_payment_auth_context": lambda r: {"gemini_api_key": None, "vertex_project": None,
                                               "vertex_region": None, "auth_method": "server"},
        "_billing_intent_error_response": lambda r: None,
        "_validate_vertex_params": lambda *a: (None, None),
        "_validate_vertex_project_id": lambda p: (p, None),
        "_validate_vertex_project_binding": lambda p, e: None,
        "resolve_model_defaults": lambda e, l, ocr_only=False, notebook_mode=False:
            (["gemini-3.1-flash-lite"], "gemini-3.1-flash-lite"),
        "current_request_id": lambda: "rid-1",
        "build_request_analytics_context": lambda *a, **k: {"request_id": "rid-1"},
        "_preflight_user_prompt": lambda p, e: (None, None),
        "quota_keys_for_request": lambda *a, **k: ["gemini-3.1-flash-lite"],
        "check_and_reserve_quotas": lambda e, k: (True, {}, None),
        "release_quotas": lambda e, k: STATE.setdefault("released", []).extend(k),
        "_error_payload": lambda code, err, **k: {"error": err, "error_code": code},
        "_error_response": lambda code, err, status=500, **k: Resp(
            {"error": err, "error_code": code}, status),
        "current_payment_inference": lambda request_scope=False: "not_processed",
        "RESPONSE_HOST_NAME": "VoucherVisionGO",
        "OrderedDict": __import__("collections").OrderedDict,
        "OrderedJsonEncoder": __import__("json").JSONEncoder,
        "build_usage_event": lambda **k: {"success": True},
        "record_usage_event": lambda e: None,
        "persist_usage_events_and_rollups": lambda *a, **k: None,
        "_rate_limit_field_prefix": lambda k: "gemini_general_access",
        "GEMINI_GENERAL_ACCESS_PREFIX": "gemini_general_access",
        "RATE_LIMIT_LABELS": {"gemini_general_access": "General Access"},
        "_send_general_access_cap_alert": lambda *a, **k: None,
        "_send_rate_limit_hit_alert": lambda *a, **k: None,
        "_send_pro_migration_advisory": lambda *a, **k: None,
        "read_rate_limit_state": lambda e: {},
        "app": types.SimpleNamespace(config={"processor": types.SimpleNamespace(
            process_image_request=lambda file=None, **k: ({"ok": True}, 200))}),
    }
    exec(compile(ast.Module(body=picked, type_ignores=[]), "<app-slice>", "exec"), ns)
    return ns["process_image_by_url"], log


def httpx_redirect_to(target):
    def handler(url):
        if url.endswith("/start"):
            return httpx.Response(302, headers={"location": target})
        return httpx.Response(200, headers={"content-type": "image/png"}, content=png())
    return handler


print("\n=== terminal redirect failures: one attempt, no fallback, own status ===")
# These go through the REAL smart_fetch_image_as_filestorage(): its broad
# `except Exception` used to catch, retry and wrap these, which sent the
# request on to the fallback with the verdict destroyed.
for target, want, why in [
    ("http://10.0.0.5/secret", 403, "private address -> URL_BLOCKED"),
    ("http://169.254.169.254/x", 403, "cloud metadata -> URL_BLOCKED"),
    ("https://portal.test:22/x", 403, "blocked port -> URL_BLOCKED"),
    ("https://user:pw@portal.test/x", 400, "credentials -> URL_INVALID"),
    ("ftp://portal.test/x", 400, "bad scheme -> URL_INVALID"),
    ("https://nxdomain.invalid/x", 400, "unresolvable host -> URL_INVALID"),
]:
    route, log = build_route(
        "https://portal.test/start",
        requests_handler=lambda u, c: FakeRequestsResponse(
            200, {"content-type": "image/png"}, png()),
        httpx_handler=httpx_redirect_to(target))
    resp = route()
    smart_gets = [e for e in log if e[0] == "smart"]
    fallback = [e for e in log if e[0] == "requests"]
    check(f"{why:<36} -> {want}", getattr(resp, "status_code", None) == want,
          f"got {getattr(resp, 'status_code', resp)}")
    check("...one attempt at the primary, not three",
          len(smart_gets) <= 2, f"{len(smart_gets)} primary requests")
    check("...and the fallback is never invoked", not fallback,
          f"{len(fallback)} fallback calls")
    check("...quota released", STATE.get("released") == ["gemini-3.1-flash-lite"],
          str(STATE.get("released")))

print("\n=== a transient primary failure reaches the fallback ===")
attempts = {"n": 0}


def flaky_httpx(url):
    attempts["n"] += 1
    raise httpx.ConnectError("portal unreachable")


route, log = build_route(
    "https://portal.test/x.jpg",
    requests_handler=lambda u, c: FakeRequestsResponse(
        200, {"content-type": "image/png"}, png()),
    httpx_handler=flaky_httpx)
resp = route()
check("a transient primary failure falls back and succeeds",
      getattr(resp, "status_code", None) == 200, str(getattr(resp, "status_code", resp)))
check("...the fallback actually ran", any(e[0] == "requests" for e in log))
# The primary owns transient retries (max_retries=3, each doing a HEAD then a
# GET = 6 requests). The route makes a single pass, so a second retry layer
# would show up here as ~18 requests rather than ~6.
check("only one layer retries: no route-level multiplication",
      attempts["n"] <= 6, f"{attempts['n']} primary HTTP requests (3 attempts x HEAD+GET)")
check("the route loop is a single pass", "max_retries = 1" in SRC)

print("\n=== the primary succeeds on its own, without the fallback ===")
route, log = build_route(
    "https://portal.test/x.jpg",
    requests_handler=lambda u, c: FakeRequestsResponse(500),
    httpx_handler=lambda u: httpx.Response(
        200, headers={"content-type": "image/png"}, content=png()))
resp = route()
check("the real primary downloader returns 200",
      getattr(resp, "status_code", None) == 200, str(getattr(resp, "status_code", resp)))
check("...and the fallback is not used",
      not [e for e in log if e[0] == "requests"])

print("\n=== cookie-bearing redirects through the fallback ===")


def cookie_portal(url, cookies):
    if url.endswith("/start"):
        return FakeRequestsResponse(
            302, {"location": "https://portal.test/image.jpg",
                  "_set_cookie": {"sessionid": "abc123"}})
    if cookies.get("sessionid") != "abc123":
        return FakeRequestsResponse(403, {}, b"missing session")
    return FakeRequestsResponse(200, {"content-type": "image/png"}, png())


route, log = build_route(
    "https://portal.test/start",
    requests_handler=cookie_portal,
    httpx_handler=lambda u: (_ for _ in ()).throw(httpx.ConnectError("down")))
resp = route()
check("a portal that sets a cookie on redirect still succeeds",
      getattr(resp, "status_code", None) == 200, str(getattr(resp, "status_code", resp)))
second = [e for e in log if e[0] == "requests" and e[1].endswith("image.jpg")]
check("...because the cookie was carried to the next hop",
      bool(second) and second[0][2].get("sessionid") == "abc123",
      str(second[0][2]) if second else "no second hop")

print("\n=== the FALLBACK validates its own redirects too ===")
# The primary fails transiently, so the fallback does the fetching — and it
# must apply the same destination rules. Otherwise a destination refused by
# one path is reachable through the other.
for target, want, why in [
    ("http://10.0.0.5/secret", 403, "private address"),
    ("http://169.254.169.254/x", 403, "cloud metadata"),
    ("https://user:pw@portal.test/x", 400, "embedded credentials"),
]:
    def fallback_redirect(url, cookies, _t=target):
        if url.endswith("/start"):
            return FakeRequestsResponse(302, {"location": _t})
        return FakeRequestsResponse(200, {"content-type": "image/png"}, png())

    route, log = build_route(
        "https://portal.test/start",
        requests_handler=fallback_redirect,
        httpx_handler=lambda u: (_ for _ in ()).throw(httpx.ConnectError("primary down")))
    resp = route()
    check(f"fallback redirect to {why:<22} -> {want}",
          getattr(resp, "status_code", None) == want,
          f"got {getattr(resp, 'status_code', resp)}")
    followed = [e for e in log if e[0] == "requests" and "/start" not in e[1]]
    check("...and the refused target was never fetched", not followed, str(followed))

print("\n=== spooled temp files are closed on failure ===")
import tempfile as _tempfile  # noqa: E402

SPOOLS = []
_real_spool = _tempfile.SpooledTemporaryFile


def _tracking_spool(*a, **k):
    f = _real_spool(*a, **k)
    SPOOLS.append(f)
    return f


def spool_leak_check(label, run):
    """Track every spool either downloader creates, and require all be closed."""
    SPOOLS.clear()
    import anti_bot_fetch as _abf
    _abf.tempfile.SpooledTemporaryFile = _tracking_spool
    _tempfile.SpooledTemporaryFile = _tracking_spool     # app.py's slice too
    try:
        run()
    except Exception:
        pass
    finally:
        _abf.tempfile.SpooledTemporaryFile = _real_spool
        _tempfile.SpooledTemporaryFile = _real_spool
    open_left = [f for f in SPOOLS if not getattr(f, "closed", True)]
    check(label, SPOOLS and not open_left,
          f"{len(SPOOLS)} spooled files, {len(open_left)} left open")


# A body that streams fine but is not a decodable image.
spool_leak_check(
    "a corrupt body does not leak the primary's spool",
    lambda: build_route(
        "https://portal.test/x.jpg",
        requests_handler=lambda u, c: FakeRequestsResponse(500),
        httpx_handler=lambda u: httpx.Response(
            200, headers={"content-type": "image/png"}, content=b"not an image"))[0]())


class ExplodingBody(FakeRequestsResponse):
    """Streams a chunk, then fails mid-read."""

    def iter_content(self, chunk_size=None):
        yield b"\x89PNG"
        raise IOError("connection reset mid-body")


spool_leak_check(
    "a read failure does not leak the fallback's spool",
    lambda: build_route(
        "https://portal.test/x.jpg",
        requests_handler=lambda u, c: ExplodingBody(200, {"content-type": "image/png"}),
        httpx_handler=lambda u: (_ for _ in ()).throw(httpx.ConnectError("primary down")))[0]())

spool_leak_check(
    "a corrupt body does not leak the fallback's spool",
    lambda: build_route(
        "https://portal.test/x.jpg",
        requests_handler=lambda u, c: FakeRequestsResponse(
            200, {"content-type": "image/png"}, b"not an image"),
        httpx_handler=lambda u: (_ for _ in ()).throw(httpx.ConnectError("primary down")))[0]())

# On the fallback's no-resize path the spool IS the returned FileStorage's
# stream, so nothing downstream closes it — the route must.
spool_leak_check(
    "the route closes the FileStorage it was handed (success path)",
    lambda: build_route(
        "https://portal.test/x.jpg",
        requests_handler=lambda u, c: FakeRequestsResponse(
            200, {"content-type": "image/png"}, png()),
        httpx_handler=lambda u: (_ for _ in ()).throw(httpx.ConnectError("primary down")))[0]())

print(f"\n{'ALL PASS' if not fails else str(fails) + ' FAILED'}")
sys.exit(1 if fails else 0)

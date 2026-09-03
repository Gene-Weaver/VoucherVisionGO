"""Behavioural tests for the URL safety guards.

Drives the real guarded_fetch module: the fetch deadline, URL shape rules,
public-address resolution and the optional allowlist. The downloader itself is
anti_bot_fetch.py, which these guards run in front of.

Needs httpx:  ./.venv_cors/bin/python tests/tests_guarded_fetch.py
"""
import io
import os
import sys
import time

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

import httpx  # noqa: E402
import guarded_fetch as _gf  # noqa: E402
from guarded_fetch import _getaddrinfo_bounded as _resolve_with_timeout  # noqa: E402
from guarded_fetch import (  # noqa: E402
    BlockedDestination, FetchDeadlineExceeded, InvalidFetchUrl,
    address_is_public, resolve_public_addresses, validate_url_shape,
)

fails = 0


def check(label, cond, detail=""):
    global fails
    fails += not cond
    print(f"{'PASS' if cond else 'FAIL'}  {label:<58} {detail}")


def raises(fn, exc_type):
    try:
        fn()
    except exc_type as e:
        return e
    except Exception as e:
        return ("WRONG TYPE", type(e).__name__, str(e)[:60])
    return None


PUBLIC = ["93.184.216.34"]
PRIVATE = ["10.0.0.5"]


def resolver_for(mapping):
    def resolve(host):
        if host not in mapping:
            raise OSError(f"no such host {host}")
        return mapping[host]
    return resolve


def client_for(handler):
    return httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=False)


print("=== DNS resolution is bounded, not left to block indefinitely ===")
# getaddrinfo has no timeout of its own, so a slow resolver could block far
# past any HTTP timeout. It runs on a small shared pool under a deadline.
import guarded_fetch as _gf  # noqa: E402
_real_getaddrinfo = _gf.socket.getaddrinfo


def _hanging_getaddrinfo(*a, **k):
    time.sleep(30)
    return [(0, 0, 0, "", ("93.184.216.34", 0))]


_gf.socket.getaddrinfo = _hanging_getaddrinfo
try:
    start = time.monotonic()
    err = raises(lambda: _resolve_with_timeout("slow.test", 0.3), FetchDeadlineExceeded)
    elapsed = time.monotonic() - start
    check("a hanging DNS lookup raises FetchDeadlineExceeded",
          isinstance(err, FetchDeadlineExceeded),
          type(err).__name__ if err else "no raise")
    check("...at the timeout, not after the resolver returns", elapsed < 3.0,
          f"{elapsed:.2f}s (the resolver would take 30s)")
    check("resolve_public_addresses is bounded too",
          isinstance(raises(lambda: resolve_public_addresses("slow.test"),
                            FetchDeadlineExceeded), FetchDeadlineExceeded))
    check("a bounded pool is used, not a thread per lookup",
          "ThreadPoolExecutor" in io.open(
              os.path.join(REPO_ROOT, "guarded_fetch.py"), encoding="utf-8").read())
finally:
    _gf.socket.getaddrinfo = _real_getaddrinfo


print("\n=== typed failures: a blocked destination is never a PermissionError ===")
err = raises(lambda: resolve_public_addresses("127.0.0.1"), BlockedDestination)
check("loopback raises BlockedDestination", isinstance(err, BlockedDestination))
check("...which is NOT a PermissionError",
      not isinstance(err, PermissionError), type(err).__name__)
err = raises(lambda: validate_url_shape("https://user:pw@evil.test/x"), InvalidFetchUrl)
check("credentials raise InvalidFetchUrl", isinstance(err, InvalidFetchUrl))


print("\n=== no host allowlist: the public-address rule is the boundary ===")
GF_SRC = io.open(os.path.join(REPO_ROOT, "guarded_fetch.py"), encoding="utf-8").read()
ABF_SRC = io.open(os.path.join(REPO_ROOT, "anti_bot_fetch.py"), encoding="utf-8").read()
APP_SRC = io.open(os.path.join(REPO_ROOT, "app.py"), encoding="utf-8").read()
check("host_is_allowed is gone", "def host_is_allowed" not in GF_SRC)
check("ALLOWED_IMAGE_DOMAINS is no longer read",
      all("ALLOWED_IMAGE_DOMAINS" not in src for src in (GF_SRC, ABF_SRC, APP_SRC)))
check("no allowed_domains plumbing remains",
      "allowed_domains" not in ABF_SRC and "allowed_domains" not in APP_SRC)
check("a public institutional host is still fetchable",
      resolve_public_addresses("8.8.8.8") == ["8.8.8.8"])
check("...and a private one is still refused",
      isinstance(raises(lambda: resolve_public_addresses("10.0.0.5"), BlockedDestination),
                 BlockedDestination))
check("public address classification still holds",
      address_is_public("8.8.8.8") and not address_is_public("169.254.169.254"))

print(f"\n{'ALL PASS' if not fails else str(fails) + ' FAILED'}")
sys.exit(1 if fails else 0)

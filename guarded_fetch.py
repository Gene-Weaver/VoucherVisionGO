"""Safety guards for caller-supplied image URLs.

The service fetches URLs chosen by API callers from inside Cloud Run, where the
metadata endpoint and the project's private network are reachable. This module holds the checks
applied before any such URL is fetched:

* **URL shape.** No whitespace or control characters, no embedded
  credentials, http/https only, and only ordinary web ports.
* **A destination that is publicly routable.** Every address a host resolves to
  must be public; a name resolving to both a public and a private address is
  rejected outright. This is what keeps the cloud metadata endpoint and the
  project's private network out of reach.
* **A bounded DNS lookup.** getaddrinfo has no timeout of its own, so it runs
  on a small shared pool under the request's deadline.

There is deliberately no host allowlist: VoucherVisionGO fetches from
arbitrary institutional portals, so the public-address rule is the boundary.
"""
from __future__ import annotations

import io
import ipaddress
import os
import socket
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout

# A stable, honest identifier. Institutional portals that want to contact us or
# rate-limit us can; that is preferable to impersonating a browser.

ALLOWED_PORTS = frozenset({80, 443})
DNS_TIMEOUT_SECONDS = 10.0
# Per-address connect cap. Without it a single unreachable address could spend

# Resolution runs on a small shared pool. A fresh thread per lookup would
# accumulate un-killable threads whenever DNS is slow.
_DNS_POOL = ThreadPoolExecutor(max_workers=4, thread_name_prefix="img-dns")


class GuardedFetchError(Exception):
    """Base class for every failure this module raises."""


class BlockedDestination(GuardedFetchError):
    """A URL, or a redirect target, that this server refuses to fetch.

    Its own type, not PermissionError: a filesystem permission fault and a
    blocked destination must never classify alike.
    """

    def __init__(self, message, url=None):
        super().__init__(message)
        self.message = message
        self.url = url


class InvalidFetchUrl(GuardedFetchError):
    """A caller-supplied URL that is malformed."""

    def __init__(self, message, url=None):
        super().__init__(message)
        self.message = message
        self.url = url


class FetchDeadlineExceeded(GuardedFetchError):
    """A bounded operation (currently DNS resolution) ran out of time."""




def address_is_public(ip_text):
    """True only for a globally routable unicast address."""
    try:
        ip = ipaddress.ip_address(ip_text)
    except ValueError:
        return False
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        # Redundant on CPython >= 3.13, where is_private already unwraps these.
        ip = ip.ipv4_mapped
    return not (
        ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast
        or ip.is_reserved or ip.is_unspecified
        or getattr(ip, "is_site_local", False)
    )


def _getaddrinfo_bounded(host, timeout):
    """socket.getaddrinfo on the shared pool, bounded by *timeout*.

    getaddrinfo is synchronous with no timeout of its own, so a slow resolver
    can block far past any HTTP deadline. The pool is bounded, so a run of slow
    lookups cannot accumulate threads.
    """
    future = _DNS_POOL.submit(
        lambda: [info[4][0] for info in
                 socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)])
    try:
        return future.result(timeout=timeout)
    except FuturesTimeout:
        future.cancel()
        raise FetchDeadlineExceeded(
            f"DNS resolution for {host!r} exceeded {timeout:.1f}s") from None


def resolve_public_addresses(host, resolver=None):
    """Resolve *host* to addresses that are all public.

    A name resolving to both a public and a private address is rejected
    outright rather than filtered: which one the client would pick is not ours
    to assume.
    """
    host = (host or "").strip().rstrip(".")
    if not host:
        raise InvalidFetchUrl("The supplied image URL has no host.")
    literal = host[1:-1] if host.startswith("[") and host.endswith("]") else host

    # An IP literal needs no DNS, so a resolver failure can never mask a
    # blocked address.
    try:
        ipaddress.ip_address(literal)
    except ValueError:
        pass
    else:
        if not address_is_public(literal):
            raise BlockedDestination(
                "The supplied image URL resolves to a non-public address, "
                "which this server will not fetch.", url=host)
        return [literal]

    resolve = resolver or (lambda h: _getaddrinfo_bounded(h, DNS_TIMEOUT_SECONDS))
    try:
        addresses = sorted(set(resolve(literal)))
    except (FetchDeadlineExceeded, BlockedDestination):
        raise
    except Exception as exc:
        raise InvalidFetchUrl(
            "The supplied image URL's host could not be resolved.", url=host) from exc
    if not addresses:
        raise InvalidFetchUrl(
            "The supplied image URL's host could not be resolved.", url=host)
    for address in addresses:
        if not address_is_public(address):
            raise BlockedDestination(
                "The supplied image URL resolves to a non-public address, "
                "which this server will not fetch.", url=host)
    return addresses


def validate_url_shape(url):
    """Reject malformed URLs before anything touches the network."""
    raw = url or ""
    if not raw.strip():
        raise InvalidFetchUrl("No image URL provided.")
    stripped = raw.strip()
    if any(ch.isspace() or ord(ch) < 0x20 or ord(ch) == 0x7F for ch in stripped):
        raise InvalidFetchUrl(
            "The supplied image URL contains whitespace or control characters.")
    try:
        parsed = urllib.parse.urlparse(stripped)
    except Exception as exc:
        raise InvalidFetchUrl("The supplied image URL is not a valid URL.") from exc
    if parsed.scheme.lower() not in ("http", "https"):
        raise InvalidFetchUrl("The supplied image URL must use http or https.")
    if parsed.username or parsed.password or "@" in (parsed.netloc or ""):
        raise InvalidFetchUrl(
            "The supplied image URL must not contain embedded credentials.")
    try:
        port = parsed.port
    except ValueError:
        raise InvalidFetchUrl("The supplied image URL has an invalid port.") from None
    if port is not None and port not in ALLOWED_PORTS:
        raise BlockedDestination(
            "The supplied image URL uses a port this server will not fetch.")
    if not parsed.hostname:
        raise InvalidFetchUrl("The supplied image URL has no host.")
    return parsed





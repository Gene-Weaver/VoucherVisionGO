# anti_bot_fetch.py
from __future__ import annotations
import io
import os
import tempfile
import re
import time
import random
import urllib.parse
from typing import Iterable, Optional, Tuple, Callable

import httpx
from PIL import Image
from werkzeug.datastructures import FileStorage

# ---------------------
# Browser-like defaults
# ---------------------
_DEFAULT_UAS: list[str] = [
    # Reasonable, current desktop user-agents. Rotate to reduce heuristic flags.
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 13_5) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.3 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:119.0) Gecko/20100101 Firefox/119.0",
]

_DEFAULT_HEADERS = {
    # mimic image fetch from a real browser tab
    "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
    "DNT": "1",
    # Note: Referer is set dynamically per request (site root)
}

# ------------ Utilities ------------
def _site_referer(url: str) -> str:
    """Use the scheme://host/ as a sane Referer default."""
    u = urllib.parse.urlparse(url)
    return f"{u.scheme}://{u.netloc}/"

def _choose_ua(custom_ua: Optional[str]) -> str:
    if custom_ua:
        return custom_ua
    return random.choice(_DEFAULT_UAS)

def _filename_from_url(url: str) -> str:
    """Best-effort filename from URL path; fallback to sanitized host-based name."""
    path = urllib.parse.urlparse(url).path
    name = os.path.basename(path) or "downloaded"
    name = re.sub(r"[^\w.\-]+", "_", name)
    return name

def _fits_pixel_budget(image: Image.Image, max_pixels: int) -> bool:
    w, h = image.size
    return (w * h) <= max_pixels

def _resize_to_max_pixels(img: Image.Image, max_pixels: int) -> Image.Image:
    import math
    w, h = img.size
    cur = w * h
    if cur <= max_pixels:
        return img
    scale = math.sqrt(max_pixels / float(cur))
    nw, nh = max(1, int(w * scale)), max(1, int(h * scale))
    return img.resize((nw, nh), Image.Resampling.LANCZOS)

# --------------- Core fetch ---------------
class HostPacer:
    """Simple in-proc per-host pacer to avoid hammering portals."""
    def __init__(self, min_interval_s: float = 0.75):
        self.min_interval_s = min_interval_s
        self._last = {}

    def sleep_if_needed(self, host: str):
        now = time.time()
        last = self._last.get(host, 0.0)
        delta = now - last
        if delta < self.min_interval_s:
            time.sleep(self.min_interval_s - delta + random.uniform(0.05, 0.25))
        self._last[host] = time.time()

_pacer = HostPacer()

def _sleep_with_retry_after(retry_after: Optional[str], base_delay: float, jitter: float) -> None:
    if retry_after:
        try:
            # Can be seconds or a HTTP date; handle seconds form here
            secs = float(retry_after)
            time.sleep(secs + random.uniform(0, 0.25))
            return
        except Exception:
            pass
    time.sleep(base_delay + random.uniform(0, jitter))

def _is_image_content_type(ct: Optional[str]) -> bool:
    return bool(ct and ct.lower().startswith("image/"))

def _pick_format_and_filename(filename: str, pil_img: Image.Image) -> Tuple[str, str]:
    """Return (format, filename) ensuring JPEG or PNG final."""
    lower = filename.lower()
    if lower.endswith(".png"):
        return "PNG", filename
    if lower.endswith(".jpg") or lower.endswith(".jpeg"):
        return "JPEG", filename
    # derive from mode; prefer PNG if transparency
    if "A" in pil_img.getbands():
        return "PNG", (os.path.splitext(filename)[0] + ".png")
    return "JPEG", (os.path.splitext(filename)[0] + ".jpg")

# Bodies are streamed into a spooled temp file: small images stay in memory,
# large ones spill to disk instead of being buffered whole. This is a memory
# measure only — there is no size limit.
SPOOL_MAX_IN_MEMORY_BYTES = 8 * 1024 * 1024


def _open_validated(client, url, destination_check, max_redirects, logger=None):
    """Open a streaming GET on *url*, validating every redirect hop.

    Returns (response_cm, response, final_url). The caller owns the context
    manager and must exit it, which closes the response and returns the
    connection to the pool.

    `destination_check` raises on a destination this server will not follow.
    Its exception propagates unchanged, so the caller's own verdict (400 vs
    403 vs 504) survives instead of collapsing into one.
    """
    current = url
    for hop in range(max_redirects + 1):
        cm = client.stream("GET", current)
        resp = cm.__enter__()
        if resp.status_code not in (301, 302, 303, 307, 308):
            return cm, resp, current
        location = resp.headers.get("location")
        cm.__exit__(None, None, None)      # redirect hop: release it now
        if not location:
            return None, resp, current
        nxt = str(httpx.URL(current).join(location))
        if destination_check is not None:
            destination_check(nxt)          # raises on a refused destination
        if logger:
            logger.info(f"redirect {hop + 1}: {current} -> {nxt}")
        current = nxt
    raise RuntimeError(f"Too many redirects while fetching {url}")


def smart_fetch_image_as_filestorage(
    url: str,
    *,
    max_pixels: int = 5_200_000,
    max_retries: int = 5,
    connect_timeout: float = 15.0,
    read_timeout: float = 60.0,
    per_try_base_delay: float = 0.6,
    per_try_jitter: float = 0.6,
    destination_check: Optional[Callable] = None,
    terminal_exceptions: Tuple[type, ...] = (),
    max_redirects: int = 5,
    user_agent: Optional[str] = None,
    extra_headers: Optional[dict] = None,
    cookie: Optional[str] = None,
    logger=None,
) -> Tuple[FileStorage, str]:
    """
    Robust, browser-like fetch -> PIL -> optional resize -> FileStorage.
    - HTTP/2 client (httpx), follow redirects, cookie jar, per-host pacing
    - Honors 429 Retry-After
    - Rotates/sets UA and Referer, sends realistic Accept headers
    """
    parsed = urllib.parse.urlparse(url)
    host = parsed.netloc

    if destination_check is not None:
        destination_check(url)              # raises on a refused destination

    # Compose headers
    headers = dict(_DEFAULT_HEADERS)
    headers["User-Agent"] = _choose_ua(user_agent)
    headers["Referer"] = headers.get("Referer") or _site_referer(url)
    if extra_headers:
        headers.update({k: str(v) for k, v in extra_headers.items()})

    # Session
    jar = httpx.Cookies()
    if cookie:
        # e.g., "sessionid=abc123; other=xyz"
        for part in cookie.split(";"):
            part = part.strip()
            if "=" in part:
                k, v = part.split("=", 1)
                jar.set(k.strip(), v.strip(), domain=host)

    # httpx.Timeout requires a positional default or all four fields; the
    # keyword-only form raises ValueError before the retry loop, which is why
    # this fetcher never ran and every request silently used the caller's
    # fallback instead.
    timeouts = httpx.Timeout(read_timeout, connect=connect_timeout)
    # follow_redirects=False: httpx would otherwise follow a redirect to a
    # private or link-local address without `destination_check` ever seeing it.
    # Redirects are walked manually below, validating every hop. The Client
    # keeps its cookie jar across hops, so portal session cookies survive.
    last_exc = None
    filename = _filename_from_url(url)

    # Context-managed so the connection pool is released on every path,
    # including the terminal re-raise above.
    with httpx.Client(http2=True, headers=headers, cookies=jar,
                      follow_redirects=False, timeout=timeouts) as client:
        for attempt in range(1, max_retries + 1):
            try:
                # Soft pacing per host
                _pacer.sleep_if_needed(host)

                # HEAD first (helps some portals & gets type/length), but tolerate 405
                head_resp = None
                try:
                    head_resp = client.head(url)
                    if logger:
                        logger.info(f"HEAD {url} → {head_resp.status_code}")
                    if head_resp.status_code == 429:
                        _sleep_with_retry_after(head_resp.headers.get("Retry-After"), per_try_base_delay * attempt, per_try_jitter)
                        continue
                except Exception:
                    # skip HEAD failures — proceed to GET
                    head_resp = None

                # GET (streamed; the body is read below into a spooled file)
                resp_cm, resp, _final_url = _open_validated(
                    client, url, destination_check, max_redirects, logger)
                if logger:
                    logger.info(f"GET {url} → {resp.status_code}")

                if resp.status_code == 429:
                    # Too Many Requests → respect Retry-After
                    if resp_cm is not None:
                        resp_cm.__exit__(None, None, None)
                    _sleep_with_retry_after(resp.headers.get("Retry-After"), per_try_base_delay * attempt, per_try_jitter)
                    continue

                if 500 <= resp.status_code < 600:
                    # transient server error
                    if resp_cm is not None:
                        resp_cm.__exit__(None, None, None)
                    _sleep_with_retry_after(None, per_try_base_delay * attempt, per_try_jitter)
                    continue

                if resp.status_code == 403:
                    if logger:
                        # The body is not read here: the response is streamed,
                        # and reading it would consume the stream.
                        logger.error(
                            f"403 Forbidden for {url}\n"
                            f"  Response Headers: {dict(resp.headers)}\n"
                            f"  Request User-Agent: {headers.get('User-Agent', 'N/A')}"
                        )
                try:
                    resp.raise_for_status()
                except Exception:
                    # Close the streamed response before the retry loop's
                    # handlers take over, or the connection leaks.
                    if resp_cm is not None:
                        resp_cm.__exit__(None, None, None)
                    raise

                # Content-type check (be lenient: some servers omit it)
                ct = resp.headers.get("Content-Type", "")
                if ct and not _is_image_content_type(ct):
                    # Some portals serve through HTML landing; try to follow image src if present (lightweight heuristic)
                    # Avoid heavy parsing to keep deps light; user can pass direct image endpoints preferably.
                    if logger:
                        logger.warning(f"Non-image Content-Type '{ct}' for {url}")
                    # still try to open as image — many serve image/* without CT set, or with octet-stream
                # Stream into a seekable spooled file: small images stay in
                # memory, large ones spill to disk rather than being buffered
                # whole. No size limit is imposed.
                spool = tempfile.SpooledTemporaryFile(
                    max_size=SPOOL_MAX_IN_MEMORY_BYTES, mode="w+b")
                try:
                    try:
                        for chunk in resp.iter_bytes():
                            spool.write(chunk)
                        spool.seek(0)
                    finally:
                        if resp_cm is not None:
                            resp_cm.__exit__(None, None, None)
                    # PIL open
                    img = Image.open(spool)
                    img.load()  # force decode to catch errors early

                    # Resize if needed
                    if not _fits_pixel_budget(img, max_pixels):
                        img = _resize_to_max_pixels(img, max_pixels)

                    # Decide format & filename
                    fmt, out_name = _pick_format_and_filename(filename, img)

                    # Convert for JPEG if needed
                    if fmt == "JPEG" and img.mode not in ("L", "RGB"):
                        # flatten alpha on white
                        bg = Image.new("RGB", img.size, (255, 255, 255))
                        if img.mode in ("RGBA", "LA"):
                            alpha = img.split()[-1]
                            bg.paste(img.convert("RGBA"), mask=alpha)
                        else:
                            bg.paste(img.convert("RGB"))
                        img = bg

                    # Save to bytes
                    buf = io.BytesIO()
                    save_kwargs = {"format": fmt}
                    if fmt == "JPEG":
                        save_kwargs.update(dict(quality=95, optimize=True))
                    img.save(buf, **save_kwargs)
                    buf.seek(0)

                    fs = FileStorage(stream=buf, filename=out_name,
                                     content_type=f"image/{fmt.lower()}")
                    return fs, out_name
                finally:
                    # Closed on every path, including a failed download or a
                    # decode error: the image has been re-encoded into `buf`,
                    # so the spool (and its temp file, if it spilled) is done.
                    spool.close()

            except terminal_exceptions:
                # A refused or malformed destination — including one reached by
                # redirect — is settled. Retrying cannot change it, and wrapping it
                # in RuntimeError would destroy the caller's 400/403/504 verdict
                # and send the request on to a fallback that would re-attempt what
                # we already refused.
                raise

            except httpx.HTTPStatusError as e:
                last_exc = e
                if logger:
                    logger.warning(f"Attempt {attempt}/{max_retries} status error: {e}")
                _sleep_with_retry_after(None, per_try_base_delay * attempt, per_try_jitter)

            except (httpx.ConnectError, httpx.ReadError, httpx.TimeoutException) as e:
                last_exc = e
                if logger:
                    logger.warning(f"Attempt {attempt}/{max_retries} network error: {e}")
                _sleep_with_retry_after(None, per_try_base_delay * attempt, per_try_jitter)

            except Exception as e:
                last_exc = e
                if logger:
                    logger.exception(f"Attempt {attempt}/{max_retries} unexpected error")
                _sleep_with_retry_after(None, per_try_base_delay * attempt, per_try_jitter)

    # All retries exhausted (the client is closed by the `with` above)
    raise RuntimeError(f"Failed to fetch image after {max_retries} attempts: {last_exc}")

# anti_bot_fetch.py
from __future__ import annotations
import io
import os
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

def smart_fetch_image_as_filestorage(
    url: str,
    *,
    max_pixels: int = 5_200_000,
    max_retries: int = 5,
    connect_timeout: float = 15.0,
    read_timeout: float = 60.0,
    per_try_base_delay: float = 0.6,
    per_try_jitter: float = 0.6,
    allowed_domains: Optional[Iterable[str]] = None,
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
    - Optional allowlist to avoid accidental abuse
    """
    parsed = urllib.parse.urlparse(url)
    host = parsed.netloc

    if allowed_domains:
        allow = any(host.endswith(ad) for ad in allowed_domains)
        if not allow:
            raise PermissionError(f"Host '{host}' is not in allowed_domains")

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

    timeouts = httpx.Timeout(connect=connect_timeout, read=read_timeout)
    client = httpx.Client(http2=True, headers=headers, cookies=jar, follow_redirects=True, timeout=timeouts)

    last_exc = None
    filename = _filename_from_url(url)

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

            # GET (stream)
            resp = client.get(url)
            if logger:
                logger.info(f"GET {url} → {resp.status_code}")

            if resp.status_code == 429:
                # Too Many Requests → respect Retry-After
                _sleep_with_retry_after(resp.headers.get("Retry-After"), per_try_base_delay * attempt, per_try_jitter)
                continue

            if 500 <= resp.status_code < 600:
                # transient server error
                _sleep_with_retry_after(None, per_try_base_delay * attempt, per_try_jitter)
                continue

            resp.raise_for_status()

            # Content-type check (be lenient: some servers omit it)
            ct = resp.headers.get("Content-Type", "")
            if ct and not _is_image_content_type(ct):
                # Some portals serve through HTML landing; try to follow image src if present (lightweight heuristic)
                # Avoid heavy parsing to keep deps light; user can pass direct image endpoints preferably.
                if logger:
                    logger.warning(f"Non-image Content-Type '{ct}' for {url}")
                # still try to open as image — many serve image/* without CT set, or with octet-stream
            raw = resp.content

            # PIL open
            img = Image.open(io.BytesIO(raw))
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

            fs = FileStorage(stream=buf, filename=out_name, content_type=f"image/{fmt.lower()}")
            return fs, out_name

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

    # All retries exhausted
    raise RuntimeError(f"Failed to fetch image after {max_retries} attempts: {last_exc}")

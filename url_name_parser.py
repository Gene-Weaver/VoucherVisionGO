import hashlib
import os
import re
from email.message import Message
from urllib.parse import parse_qs, unquote, urlparse

import requests


GENERIC_WORDS = {
    "full", "native", "large", "default", "original", "format", "preview",
    "thumb", "thumbnail", "web", "webview", "imagefullview",
    "imagedownload", "download",
}
VALID_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".tiff"}


def _sanitize_filename(filename):
    """Return a safe basename while retaining useful specimen identifiers."""
    if not filename:
        return None
    filename = unquote(str(filename)).replace("\\", "/")
    filename = os.path.basename(filename).replace("\x00", "").strip().strip("'\"")
    filename = re.sub(r"[^A-Za-z0-9._-]+", "_", filename).strip("._")
    return filename or None


def _content_disposition_filename(content_disposition):
    """Parse both filename= and RFC 5987 filename*= response parameters."""
    if not content_disposition:
        return None
    message = Message()
    message["Content-Disposition"] = content_disposition
    return _sanitize_filename(message.get_filename())


def _best_match(url, server_filename):
    """Find the longest continuous substring shared by a URL and filename."""
    url_text = unquote(url or "")
    server_base, server_ext = os.path.splitext(server_filename)
    best_match = ""
    for i in range(len(server_base)):
        for j in range(i + 6, len(server_base) + 1):
            substring = server_base[i:j]
            if substring in url_text and len(substring) > len(best_match):
                best_match = substring
    if not best_match:
        return None
    return _sanitize_filename(best_match + (server_ext or ".jpg"))


def extract_best_match(url, server_filename, debug=False):
    """Compatibility wrapper for callers that already have a server filename."""
    server_filename = _sanitize_filename(server_filename) or "downloaded.jpg"
    match = _best_match(url, server_filename)
    if debug:
        print(f"    [debug] Server-declared filename for matching: {server_filename}")
        if match:
            print(f"    [debug] Best substring match: {match}")
    return match or server_filename


def _obvious_filename(url, debug=False):
    """Return an explicit, non-generic filename in a URL or nested URL."""
    parsed = urlparse(unquote(url or ""))
    fallback_name = _sanitize_filename(os.path.basename(parsed.path))
    if fallback_name:
        base, extension = os.path.splitext(fallback_name)
        if (
            extension.lower() in VALID_EXTENSIONS
            and not any(word in base.lower() for word in GENERIC_WORDS)
            and re.fullmatch(r"[A-Za-z0-9._-]+", base)
            and re.search(r"\d", base)
        ):
            return fallback_name

    if parsed.query:
        query_params = parse_qs(parsed.query)
        nested_parameter_names = {"url", "src", "image", "file", "path", "link"}
        for parameter, values in query_params.items():
            if parameter.lower() not in nested_parameter_names:
                continue
            nested_url = values[0]
            nested_name = _sanitize_filename(
                os.path.basename(urlparse(unquote(nested_url)).path)
            )
            if not nested_name:
                continue
            nested_base, nested_extension = os.path.splitext(nested_name)
            if (
                nested_extension.lower() in VALID_EXTENSIONS
                and not any(word in nested_base.lower() for word in GENERIC_WORDS)
            ):
                if debug:
                    print(f"Using filename from nested URL: {nested_name}")
                return nested_name
    return None


def _path_identifier(url):
    """Find the strongest specimen-like identifier in a URL path."""
    path_parts = urlparse(unquote(url or "")).path.strip("/").split("/")

    # Prefer an actual image filename, including numeric institutional IDs.
    for part in reversed(path_parts):
        candidate = _sanitize_filename(part)
        if not candidate or any(word in candidate.lower() for word in GENERIC_WORDS):
            continue
        base, extension = os.path.splitext(candidate)
        if (
            extension.lower() in VALID_EXTENSIONS
            and re.fullmatch(r"[A-Za-z0-9._-]+", base)
            and re.search(r"\d", base)
        ):
            return candidate

    # An extension-less path component must contain both a letter and a digit;
    # this prevents IIIF path controls such as /0/ from becoming "0.jpg".
    for part in reversed(path_parts):
        # IIIF identifiers are often colon-delimited within one path segment.
        # Inspect the right-most component first so
        # herb00ic:1122841:MICH-V-1122841 resolves to MICH-V-1122841.
        pieces = list(reversed(re.split(r"[:;]", part)))
        if len(pieces) == 1:
            pieces = [part]
        for piece in pieces:
            candidate = _sanitize_filename(piece)
            if not candidate or any(word in candidate.lower() for word in GENERIC_WORDS):
                continue
            if (
                re.fullmatch(r"[A-Za-z0-9._-]+", candidate)
                and re.search(r"[A-Za-z]", candidate)
                and re.search(r"\d", candidate)
            ):
                return candidate + ".jpg"
    return None


def resolve_filename_from_response(
    url, *, final_url=None, content_disposition=None, debug=False
):
    """Resolve a useful image name from already-received response metadata.

    This function performs no network requests. Downloaders should call it with
    the original URL plus the final URL and Content-Disposition they already
    received, avoiding a second HEAD request solely to determine the filename.
    """
    obvious = _obvious_filename(url, debug=debug)
    if obvious:
        return obvious

    server_filename = _content_disposition_filename(content_disposition)
    if server_filename:
        # The original URL commonly contains the clean catalog number while a
        # repository header contains a longer internal filename. Prefer their
        # longest shared identifier (for example, MICH-V-1122841).
        for candidate_url in (url, final_url):
            match = _best_match(candidate_url, server_filename)
            if match:
                if debug:
                    print(f"    [debug] Matched response filename: {match}")
                return match
        return server_filename

    if final_url and final_url != url:
        obvious = _obvious_filename(final_url, debug=debug)
        if obvious:
            return obvious

    for candidate_url in (url, final_url):
        if candidate_url:
            candidate = _path_identifier(candidate_url)
            if candidate:
                if debug:
                    print(f"    [debug] Fallback valid identifier found: {candidate}")
                return candidate

    url_hash = hashlib.md5((url or "").encode("utf-8")).hexdigest()[:12]
    fallback = f"image_{url_hash}.jpg"
    if debug:
        print(f"    [debug] No valid fallback candidate, using URL hash: {fallback}")
    return fallback


def extract_filename_from_url(url, timeout=10, debug=False):
    """Resolve an image filename, using HEAD only for legacy callers.

    Download paths that already possess response metadata should call
    ``resolve_filename_from_response`` instead.
    """
    obvious = _obvious_filename(url, debug=debug)
    if obvious:
        return obvious

    try:
        response = requests.head(url, allow_redirects=True, timeout=timeout)
        if debug:
            print(f"    [debug] HEAD status code: {response.status_code}")
        return resolve_filename_from_response(
            url,
            final_url=str(response.url),
            content_disposition=response.headers.get("content-disposition"),
            debug=debug,
        )
    except requests.RequestException as exc:
        if debug:
            print(f"    [debug] HEAD request failed: {exc}")
        return resolve_filename_from_response(url, debug=debug)


if __name__ == "__main__":
    urls = [
        "https://rmh.uwyo.edu/images/jpeg.php?Image=RM0021232.jpg&Width=2000",
        "https://img.cyverse.org/resize?width=4000&url=https://data.cyverse.org/dav-anon/iplant/projects/magnoliagrandiFLORA/images/specimens/MISS0055041/MISS0055041.JPG",
        "https://id.digitarium.fi/api/C.131915/Preview001.jpg",
        "https://oregonflora.org/imglib/OSU_V/OSC-V-269/OSC-V-269340_med.jpg",
        "https://swbiodiversity.org/imglib/h_seinet/seinet/KHD/KHD00041/KHD00041592_lg.jpg",
        "https://quod.lib.umich.edu/cgi/i/image/api/image/herb00ic:1500329:MICH-V-1500329/full/res:0/0/native.jpg",
        "https://beaty.b-cdn.net/V182378.jpg",
        "http://mediaphoto.mnhn.fr/media/1441449379108hzR2EonguMoIMGVQ",
        "https://mediaphoto.mnhn.fr/media/1550169734602JTIb5TZotc7BA4mv",
        "http://images.mobot.org/tropicosimages3/detailimages/Tropicos/131/80B7E868-D17F-4A90-8B81-FFF0BDD114D1.jpg",
        "http://sweetgum.nybg.org/images3/521/802/01449954.jpg",
        "https://medialib.naturalis.nl/file/id/L.3800382/format/large",
        "http://mam.ansp.org/image/PH/Fullsize/00563/PH00563758.jpg",
        "http://sweetgum.nybg.org/images3/521/802/01449954.jpg",
        "http://d2seqvvyy3b8p2.cloudfront.net/99e137a4582d0e5179f5dd3fa412a2bf.jpg",
        "https://id.digitarium.fi/api/C.131915/Preview001.jpg",
    ]

    debug = False

    for url in urls:
        print(f"URL: {url}")
        try:
            filename = extract_filename_from_url(url, debug=debug)
            print(f"  ➔ Extracted filename: {filename}\n")
        except Exception as exc:
            print(f"  ➔ Error extracting filename: {exc}\n")

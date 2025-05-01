import re
import requests
import hashlib
from urllib.parse import urlparse, unquote
import os

def extract_best_match(url, server_filename, debug=False):
    """
    Find the longest continuous substring between URL and server-declared filename.
    """
    url_text = unquote(url)
    server_base = os.path.splitext(server_filename)[0]
    
    if debug:
        print(f"    [debug] Server-declared filename for matching: {server_base}")

    best_match = ''
    for i in range(len(server_base)):
        for j in range(i + 6, len(server_base) + 1):  # window length ≥ 6
            substr = server_base[i:j]
            if substr in url_text and len(substr) > len(best_match):
                best_match = substr

    if best_match:
        if debug:
            print(f"    [debug] Best substring match: {best_match}")
        return best_match + '.jpg'  # assume jpg

    return server_filename

def extract_filename_from_url(url, timeout=10, debug=False):
    """
    Intelligently extract the real image filename from a URL using both
    server headers and path-based matching.

    """
    generic_words = {'full', 'native', 'large', 'default', 'original', 'format', 'preview', 'thumb', 'thumbnail', 'web'}
    valid_extensions = {'.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp', '.tiff'}

    parsed = urlparse(unquote(url))
    path = parsed.path
    fallback_name = os.path.basename(path)

    # First pass: parts that already have a valid extension
    # If the jpg is just the last part
    base, ext_candidate = os.path.splitext(fallback_name)
    # Reject if any generic word appears inside the part
    if any(generic in base.lower() for generic in generic_words):
        pass
    else:
        if ext_candidate.lower() in valid_extensions:
            # Base must have digits and valid characters
            if re.fullmatch(r'[A-Za-z0-9._-]+', base) and re.search(r'\d', base):
                return fallback_name

    # See if the name is in the head (MICH)
    try:
        response = requests.head(url, allow_redirects=True, timeout=timeout)
        if debug:
            print(f"    [debug] HEAD status code: {response.status_code}")
            for k, v in response.headers.items():
                if 'filename' in v or 'filename' in k.lower():
                    print(f"    [debug] HEAD {k}: {v}")

        if 'content-disposition' in response.headers:
            disp = response.headers['content-disposition']
            match = re.search(r'filename="?([^";]+)"?', disp)
            if match:
                server_filename = match.group(1)
                if debug:
                    print(f"    [debug] Server-declared full filename (raw): {server_filename}")
                return extract_best_match(url, server_filename, debug=debug)
    except requests.RequestException as e:
        if debug:
            print(f"    [debug] HEAD request failed: {e}")


    path_parts = path.strip('/').split('/')
    fallback_candidate = None


    for part in reversed(path_parts):
        part_lower = part.lower()
        base, ext_candidate = os.path.splitext(part_lower)

        # Reject if any generic word appears inside the part
        if any(generic in part_lower for generic in generic_words):
            continue

        if ext_candidate.lower() in valid_extensions:
            # Base must have digits and valid characters
            if re.fullmatch(r'[A-Za-z0-9._-]+', base) and re.search(r'\d', base):
                fallback_candidate = part
                break

    # Second pass: parts without extension
    if not fallback_candidate:
        for part in reversed(path_parts):
            part_lower = part.lower()
            base = part_lower  # no splitting

            if any(generic in base for generic in generic_words):
                continue

            if re.fullmatch(r'[A-Za-z0-9._-]+', base) and re.search(r'\d', base):
                fallback_candidate = part + '.jpg'
                break

    if fallback_candidate:
        fallback_name = fallback_candidate
        if debug:
            print(f"    [debug] Fallback valid identifier found: {fallback_candidate}")
    else:
        url_hash = hashlib.md5(url.encode('utf-8')).hexdigest()[:12]
        fallback_name = f"image_{url_hash}.jpg"
        if debug:
            print(f"    [debug] No valid fallback candidate, using URL hash: {fallback_name}")
    # Final cleanup: only allow one dot (the extension separator)
    if fallback_name.count('.') > 1:
        base, ext = fallback_name.rsplit('.', 1)
        base = base.replace('.', '-')  # replace internal periods
        fallback_name = f"{base}.{ext}"
        
    if debug:
        print(f"    [debug] Fallback basename from path: {fallback_name}")

    return fallback_name




if __name__ == "__main__":
    urls = [
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
        except Exception as e:
            print(f"  ➔ Error extracting filename: {e}\n")
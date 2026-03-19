import os
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from google.cloud import storage

BUCKET = "vouchervision-cop90-rasters"
PREFIX = "COP90"
SRC_DIR = Path("/data/COP90_Standalone/data/COP90_hh")
WORKERS = 16

client = storage.Client(project="directed-curve-401601")
bucket = client.bucket(BUCKET)

tiles = sorted(SRC_DIR.glob("*.tif"))
total = len(tiles)
print(f"Uploading {total} tiles...", flush=True)

def upload(p):
    blob = bucket.blob(f"{PREFIX}/{p.name}")
    blob.upload_from_filename(str(p))
    return p.name

done = 0
errors = 0
with ThreadPoolExecutor(max_workers=WORKERS) as ex:
    futures = {ex.submit(upload, p): p for p in tiles}
    for f in as_completed(futures):
        done += 1
        try:
            f.result()
        except Exception as e:
            errors += 1
            print(f"  ERROR {futures[f].name}: {e}", flush=True)
        if done % 500 == 0 or done == total:
            print(f"  {done}/{total} done ({errors} errors)", flush=True)

print("Done.", flush=True)

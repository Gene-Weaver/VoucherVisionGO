# WFO Backbone Database Build

This directory contains the raw World Flora Online (WFO) data and the script to build the SQLite database used for local taxonomy lookups.

## Setup (twice a year, when WFO releases a new version)

### 1. Download the latest `_uber.zip`

Go to https://doi.org/10.5281/zenodo.7460141 (always resolves to the latest version) and download `_uber.zip`.

### 2. Extract `classification.csv`

```bash
cd VoucherVisionGO/WFO_uber
mkdir uber_YYYY_MM          # e.g., uber_2026_06
unzip ~/Downloads/_uber.zip classification.csv -d uber_YYYY_MM/
```

### 3. Build the database

```bash
python build_wfo_db.py --source uber_YYYY_MM --output ../wfo_backbone.db
```

This takes 2-5 minutes and produces `wfo_backbone.db` in the VoucherVisionGO repo root.

### 4. Rebuild the Docker image

```bash
# wfo_backbone.db is included via COPY . . in the Dockerfile
# Docker layer caching skips this if the .db file hasn't changed
gcloud builds submit ...
```

## Data License

WFO Plant List data is [CC0 1.0 Universal (Public Domain)](https://creativecommons.org/publicdomain/zero/1.0/).

## Citation

> WFO (2026): World Flora Online. Published on the Internet; http://www.worldfloraonline.org.

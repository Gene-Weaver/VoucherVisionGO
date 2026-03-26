#!/usr/bin/env python3
"""
Build the WFO backbone SQLite database from the classification.csv in the uber archive.

Usage:
    cd VoucherVisionGO/WFO_uber
    python build_wfo_db.py                              # uses uber_2026_03/ by default
    python build_wfo_db.py --source uber_2026_06        # specify a different folder
    python build_wfo_db.py --output ../wfo_backbone.db  # specify output path

The output wfo_backbone.db should be placed in the VoucherVisionGO repo root
so that COPY . . in the Dockerfile includes it in the container image.
"""

import argparse
import csv
import json
import os
import sqlite3
import sys
import time

# Columns we extract from classification.csv
KEEP_COLUMNS = [
    "taxonID",
    "scientificName",
    "scientificNameAuthorship",
    "taxonRank",
    "family",
    "genus",
    "specificEpithet",
    "taxonomicStatus",
    "acceptedNameUsageID",
    "parentNameUsageID",
    "deprecated",
]

# Ranks used for building the hierarchy (family and above)
HIERARCHY_RANKS = frozenset([
    "kingdom", "subkingdom", "phylum", "subphylum",
    "class", "subclass", "superorder", "order", "suborder", "family",
])

SCHEMA = """
CREATE TABLE IF NOT EXISTS taxa (
    taxon_id TEXT PRIMARY KEY,
    scientific_name TEXT NOT NULL,
    scientific_name_authorship TEXT,
    full_name_plain TEXT NOT NULL,
    taxon_rank TEXT,
    family TEXT,
    genus TEXT,
    specific_epithet TEXT,
    taxonomic_status TEXT,
    accepted_name_usage_id TEXT,
    parent_name_usage_id TEXT,
    deprecated TEXT
);

CREATE TABLE IF NOT EXISTS hierarchy (
    taxon_id TEXT PRIMARY KEY,
    scientific_name TEXT NOT NULL,
    taxon_rank TEXT NOT NULL,
    parent_name_usage_id TEXT
);

CREATE TABLE IF NOT EXISTS metadata (
    key TEXT PRIMARY KEY,
    value TEXT
);
"""

INDEX_SQL = """
CREATE INDEX IF NOT EXISTS idx_full_name ON taxa(full_name_plain COLLATE NOCASE);
CREATE INDEX IF NOT EXISTS idx_scientific_name ON taxa(scientific_name COLLATE NOCASE);
CREATE INDEX IF NOT EXISTS idx_genus_epithet ON taxa(genus COLLATE NOCASE, specific_epithet COLLATE NOCASE);
CREATE INDEX IF NOT EXISTS idx_hierarchy_parent ON hierarchy(parent_name_usage_id);
"""

FTS_SQL = """
CREATE VIRTUAL TABLE IF NOT EXISTS taxa_fts USING fts5(
    full_name_plain,
    content='taxa',
    content_rowid='rowid',
    tokenize='trigram'
);
INSERT INTO taxa_fts(taxa_fts) VALUES('rebuild');
"""


def build_full_name(sci_name, authorship):
    """Concatenate scientific name and authorship."""
    parts = [s.strip() for s in (sci_name, authorship) if s and s.strip()]
    return " ".join(parts)


def build_hierarchy_cache(conn):
    """Walk parentNameUsageID chains for every family to build placement paths."""
    print("Building hierarchy cache...")

    # Load all hierarchy rows into a dict for fast parent lookups
    cur = conn.execute("SELECT taxon_id, scientific_name, taxon_rank, parent_name_usage_id FROM hierarchy")
    rows = {r[0]: {"name": r[1], "rank": r[2], "parent": r[3]} for r in cur}

    # Desired placement order (index positions matter for check_WFO compatibility)
    # [0]=kingdom [1]=phylum [2]=class [3]=order [4]=family [5]=genus [6]=species
    rank_order = ["kingdom", "phylum", "class", "order", "family"]

    cache = {}
    families = [(tid, info) for tid, info in rows.items() if info["rank"] == "family"]

    for tid, info in families:
        chain = {}
        chain["family"] = info["name"]
        parent_id = info["parent"]

        # Walk up the tree
        visited = set()
        while parent_id and parent_id in rows and parent_id not in visited:
            visited.add(parent_id)
            parent = rows[parent_id]
            r = parent["rank"]
            if r in rank_order:
                chain[r] = parent["name"]
            parent_id = parent["parent"]

        # Build the placement path in order
        path_parts = []
        for r in rank_order:
            path_parts.append(chain.get(r, ""))
        path = "|".join(path_parts)

        # Only overwrite if this path has more filled-in ranks (handles duplicate family entries)
        existing = cache.get(info["name"], "")
        if path.count("|") - path.count("||") > existing.count("|") - existing.count("||"):
            cache[info["name"]] = path
        elif info["name"] not in cache:
            cache[info["name"]] = path

    print(f"  Built placement paths for {len(cache)} families")
    return cache


def build_database(csv_path, db_path):
    """Parse classification.csv and build the SQLite database."""
    if os.path.exists(db_path):
        os.remove(db_path)

    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=OFF")
    conn.execute("PRAGMA cache_size=-512000")  # 512MB cache during build
    conn.executescript(SCHEMA)

    print(f"Reading {csv_path}...")
    t0 = time.time()
    taxa_batch = []
    hier_batch = []
    row_count = 0

    csv.field_size_limit(sys.maxsize)

    with open(csv_path, "r", encoding="utf-8", errors="replace") as f:
        reader = csv.DictReader(f)
        for row in reader:
            row_count += 1
            if row_count % 200000 == 0:
                elapsed = time.time() - t0
                print(f"  {row_count:,} rows ({elapsed:.1f}s)")

            sci_name = row.get("scientificName", "").strip()
            authorship = row.get("scientificNameAuthorship", "").strip()
            full_name = build_full_name(sci_name, authorship)
            taxon_rank = row.get("taxonRank", "").strip().lower()
            taxon_id = row.get("taxonID", "").strip()
            parent_id = row.get("parentNameUsageID", "").strip()

            taxa_batch.append((
                taxon_id,
                sci_name,
                authorship,
                full_name,
                taxon_rank,
                row.get("family", "").strip(),
                row.get("genus", "").strip(),
                row.get("specificEpithet", "").strip(),
                row.get("taxonomicStatus", "").strip(),
                row.get("acceptedNameUsageID", "").strip(),
                parent_id,
                row.get("deprecated", "").strip(),
            ))

            if taxon_rank in HIERARCHY_RANKS:
                hier_batch.append((taxon_id, sci_name, taxon_rank, parent_id))

            if len(taxa_batch) >= 50000:
                conn.executemany(
                    "INSERT OR IGNORE INTO taxa VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                    taxa_batch
                )
                if hier_batch:
                    conn.executemany(
                        "INSERT OR IGNORE INTO hierarchy VALUES (?,?,?,?)",
                        hier_batch
                    )
                taxa_batch.clear()
                hier_batch.clear()

    # Final batch
    if taxa_batch:
        conn.executemany("INSERT OR IGNORE INTO taxa VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", taxa_batch)
    if hier_batch:
        conn.executemany("INSERT OR IGNORE INTO hierarchy VALUES (?,?,?,?)", hier_batch)
    conn.commit()

    elapsed = time.time() - t0
    print(f"  Inserted {row_count:,} rows in {elapsed:.1f}s")

    # Build indexes
    print("Building indexes...")
    t1 = time.time()
    conn.executescript(INDEX_SQL)
    print(f"  Indexes built in {time.time() - t1:.1f}s")

    # Build FTS5
    print("Building FTS5 trigram index...")
    t2 = time.time()
    conn.executescript(FTS_SQL)
    print(f"  FTS5 built in {time.time() - t2:.1f}s")

    # Build hierarchy cache and store in metadata
    hierarchy_cache = build_hierarchy_cache(conn)
    conn.execute(
        "INSERT OR REPLACE INTO metadata VALUES (?, ?)",
        ("hierarchy_cache", json.dumps(hierarchy_cache))
    )
    conn.commit()

    # Compact
    print("Compacting database...")
    conn.execute("PRAGMA journal_mode=DELETE")
    conn.execute("VACUUM")
    conn.close()

    db_size_mb = os.path.getsize(db_path) / (1024 * 1024)
    total_time = time.time() - t0
    print(f"\nDone! {row_count:,} rows → {db_path} ({db_size_mb:.0f} MB) in {total_time:.0f}s")


def main():
    parser = argparse.ArgumentParser(description="Build WFO backbone SQLite database")
    parser.add_argument("--source", default="uber_2026_03",
                        help="Folder containing classification.csv (default: uber_2026_03)")
    parser.add_argument("--output", default="../wfo_backbone.db",
                        help="Output database path (default: ../wfo_backbone.db)")
    args = parser.parse_args()

    csv_path = os.path.join(args.source, "classification.csv")
    if not os.path.exists(csv_path):
        print(f"Error: {csv_path} not found. Extract _uber.zip first.")
        print(f"  unzip _uber.zip -d {args.source}/")
        sys.exit(1)

    build_database(csv_path, args.output)


if __name__ == "__main__":
    main()

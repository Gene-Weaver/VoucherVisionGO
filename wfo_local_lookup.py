"""
Local WFO (World Flora Online) taxonomy lookup using a pre-built SQLite database.

Replaces the remote WFO API with sub-millisecond local queries.
The database is built from the WFO _uber.zip Darwin Core Archive
using WFO_uber/build_wfo_db.py.
"""

import json
import os
import sqlite3

from Levenshtein import ratio
from fuzzywuzzy import fuzz


class WFOLocalLookup:
    """Local WFO name matching backed by a SQLite database."""

    NULL_DICT = {
        "WFO_exact_match": False,
        "WFO_exact_match_name": "",
        "WFO_candidate_names": "",
        "WFO_best_match": "",
        "WFO_placement": "",
        "WFO_override_OCR": False,
    }

    N_BEST_CANDIDATES = 10
    SEP = "|"

    def __init__(self, db_path):
        if not os.path.exists(db_path):
            raise FileNotFoundError(f"WFO database not found: {db_path}")

        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA query_only=ON")
        self.conn.execute("PRAGMA cache_size=-64000")  # 64MB read cache

        # Load hierarchy cache from metadata table
        row = self.conn.execute(
            "SELECT value FROM metadata WHERE key='hierarchy_cache'"
        ).fetchone()
        self.hierarchy_cache = json.loads(row["value"]) if row else {}

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def check_wfo(self, record, replace_if_success_wfo=False):
        """
        Main entry point. Takes a record dict (LLM output with scientificName,
        genus, specificEpithet, etc.) and returns a WFO result dict.

        Returns the same structure as the old WFONameMatcher.check_WFO.
        """
        primary, secondary = self._extract_input_strings(record)
        if primary is None and secondary is None:
            return self.NULL_DICT.copy()

        result = self._query_and_process(primary, secondary)
        result["WFO_override_OCR"] = False

        # Set exact match name
        if result.get("WFO_exact_match"):
            result["WFO_exact_match_name"] = result.get("WFO_best_match", "")
        else:
            result["WFO_exact_match_name"] = ""

        # Placement is already in the 7-element pipe-separated format:
        # kingdom|phylum|class|order|family|genus|species
        # (some positions may be empty, e.g., class for angiosperms)

        # Optionally override record fields with WFO data
        if result.get("WFO_exact_match") and replace_if_success_wfo:
            result["WFO_override_OCR"] = True
            placement_parts = result["WFO_placement"].split(self.SEP)
            if len(placement_parts) >= 7:
                record["order"] = placement_parts[3]
                record["family"] = placement_parts[4]
                record["genus"] = placement_parts[5]
                record["specificEpithet"] = placement_parts[6]
                record["scientificName"] = result.get("WFO_exact_match_name", "")

        return result

    # ------------------------------------------------------------------
    # Input extraction (mirrors old WFONameMatcher.extract_input_string)
    # ------------------------------------------------------------------

    def _extract_input_strings(self, record):
        """Extract primary and secondary search strings from the record."""
        if "scientificName" in record and "scientificNameAuthorship" in record:
            primary = f"{record.get('scientificName', '').strip()} {record.get('scientificNameAuthorship', '').strip()}".strip()
        elif "speciesBinomialName" in record and "speciesBinomialNameAuthorship" in record:
            primary = f"{record.get('speciesBinomialName', '').strip()} {record.get('speciesBinomialNameAuthorship', '').strip()}".strip()
        else:
            return None, None

        if "genus" in record and "specificEpithet" in record:
            secondary = " ".join(filter(None, [
                record.get("genus", "").strip(),
                record.get("specificEpithet", "").strip(),
            ])).strip()
        else:
            return None, None

        return primary or None, secondary or None

    # ------------------------------------------------------------------
    # Query logic
    # ------------------------------------------------------------------

    def _query_and_process(self, primary, secondary):
        """Two-stage matching: try primary input, then secondary."""
        # Try primary (scientificName + authorship)
        if primary:
            primary_result = self._lookup(primary)
            if primary_result.get("WFO_exact_match"):
                return primary_result

        # Try secondary (genus + specificEpithet)
        if secondary:
            secondary_result = self._lookup(secondary)
            if secondary_result.get("WFO_exact_match"):
                return secondary_result

        # Neither exact — merge candidates
        p_cands = (primary_result or {}).get("_ranked_candidates", [])
        s_cands = (secondary_result or {}).get("_ranked_candidates", [])

        if not p_cands and not s_cands:
            return primary_result if primary else (secondary_result or self.NULL_DICT.copy())

        # Combine, deduplicate, re-rank
        seen = set()
        combined = []
        for name, score in p_cands + s_cands:
            if name not in seen:
                seen.add(name)
                combined.append((name, score))
        combined.sort(key=lambda x: x[1], reverse=True)
        top = combined[: self.N_BEST_CANDIDATES]

        best_name = top[0][0] if top else ""
        placement = self._get_placement_for_name(best_name) if best_name else ""

        return {
            "WFO_exact_match": False,
            "WFO_exact_match_name": "",
            "WFO_candidate_names": [c[0] for c in top],
            "WFO_best_match": best_name,
            "WFO_placement": placement,
            "WFO_override_OCR": False,
        }

    def _lookup(self, input_string):
        """Try exact match, then fuzzy candidates for a single input string."""
        # Exact match on full_name_plain
        row = self.conn.execute(
            """SELECT * FROM taxa WHERE full_name_plain = ? COLLATE NOCASE
               ORDER BY CASE taxonomic_status
                   WHEN 'Accepted' THEN 1 WHEN 'Synonym' THEN 2 ELSE 3 END
               LIMIT 1""",
            (input_string,)
        ).fetchone()

        if not row:
            # Fallback: exact match on scientific_name alone
            row = self.conn.execute(
                """SELECT * FROM taxa WHERE scientific_name = ? COLLATE NOCASE
                   ORDER BY CASE taxonomic_status
                       WHEN 'Accepted' THEN 1 WHEN 'Synonym' THEN 2 ELSE 3 END
                   LIMIT 1""",
                (input_string,)
            ).fetchone()

        if row:
            placement = self._get_placement(row)
            return {
                "WFO_exact_match": True,
                "WFO_exact_match_name": row["full_name_plain"],
                "WFO_candidate_names": row["full_name_plain"],
                "WFO_best_match": row["full_name_plain"],
                "WFO_placement": placement,
                "WFO_override_OCR": False,
                "_ranked_candidates": [],
            }

        # No exact match — find fuzzy candidates
        candidates = self._find_candidates(input_string)
        ranked = self._rank_candidates(input_string, candidates)
        top = ranked[: self.N_BEST_CANDIDATES]
        best_name = top[0][0] if top else ""
        placement = self._get_placement_for_name(best_name) if best_name else ""

        return {
            "WFO_exact_match": False,
            "WFO_exact_match_name": "",
            "WFO_candidate_names": [c[0] for c in top] if top else "",
            "WFO_best_match": best_name,
            "WFO_placement": placement,
            "WFO_override_OCR": False,
            "_ranked_candidates": ranked,
        }

    # ------------------------------------------------------------------
    # Fuzzy candidate search
    # ------------------------------------------------------------------

    def _find_candidates(self, input_string, limit=100):
        """Find candidate names using genus-narrowed search, then FTS5 fallback."""
        candidates = []  # list of (scientific_name, full_name_plain) tuples

        # Phase 1: genus-narrowed search (no LIMIT — rank all species in genus)
        words = input_string.split()
        if words:
            genus_guess = words[0]
            rows = self.conn.execute(
                """SELECT scientific_name, full_name_plain FROM taxa
                   WHERE genus = ? COLLATE NOCASE
                   AND taxon_rank IN ('species', 'subspecies', 'variety', 'form')""",
                (genus_guess,)
            ).fetchall()
            candidates = [(r["scientific_name"], r["full_name_plain"]) for r in rows]

        # Phase 2: FTS5 trigram fallback if genus didn't match well
        if len(candidates) < 5:
            try:
                fts_rows = self.conn.execute(
                    """SELECT scientific_name, full_name_plain FROM taxa_fts
                       JOIN taxa ON taxa.rowid = taxa_fts.rowid
                       WHERE taxa_fts MATCH ?
                       ORDER BY rank LIMIT ?""",
                    (input_string, limit)
                ).fetchall()
                existing = {c[1] for c in candidates}
                candidates.extend(
                    (r["scientific_name"], r["full_name_plain"])
                    for r in fts_rows if r["full_name_plain"] not in existing
                )
            except Exception:
                pass  # FTS5 may not handle all query strings

        return candidates

    def _rank_candidates(self, query, candidates):
        """Rank candidates by combined Levenshtein + fuzzy similarity.

        Compares query against scientific_name (without authorship) for better
        ranking, but returns full_name_plain as the candidate name.
        """
        if not candidates:
            return []

        query_words = query.split()
        scored = []
        for sci_name, full_name in candidates:
            # Compare against scientific_name (no authorship) for better matching
            name_words = sci_name.split()
            word_sims = [
                ratio(qw, nw)
                for qw, nw in zip(query_words, name_words)
            ]
            word_score = sum(word_sims) if word_sims else 0
            fuzzy_score = fuzz.ratio(query, sci_name)
            combined = (word_score + fuzzy_score) / 2
            scored.append((full_name, combined))

        scored.sort(key=lambda x: x[1], reverse=True)
        return scored

    # ------------------------------------------------------------------
    # Placement / hierarchy
    # ------------------------------------------------------------------

    def _get_placement(self, row):
        """Build placement string from a taxa row using the hierarchy cache."""
        family = row["family"]
        genus = row["genus"] or ""
        sci_name = row["scientific_name"] or ""

        family_path = self.hierarchy_cache.get(family, "")
        if family_path:
            return f"{family_path}|{genus}|{sci_name}"
        elif family:
            return f"||||{family}|{genus}|{sci_name}"
        else:
            return ""

    def _get_placement_for_name(self, name):
        """Get placement for a name string by looking it up first."""
        row = self.conn.execute(
            """SELECT * FROM taxa WHERE full_name_plain = ? COLLATE NOCASE LIMIT 1""",
            (name,)
        ).fetchone()
        if row:
            return self._get_placement(row)
        return ""

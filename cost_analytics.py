"""
Cost analytics for VoucherVisionGO.

Parses GCP billing invoice CSVs (placed in gs://vouchervision-cop90-rasters/invoices/),
classifies SKUs as LLM vs overhead, extracts model identities, reconciles against
Firestore usage_statistics, and returns a JSON-serializable monthly report used by
the admin dashboard Cost Analytics tab.
"""
from __future__ import annotations

import csv
import io
import json
import logging
import os
import re
import threading
from collections import defaultdict
from datetime import datetime

logger = logging.getLogger(__name__)


class _CredentialError(Exception):
    """Raised for credential problems; message is always sanitized."""


def build_storage_client():
    """Return a google.cloud.storage.Client that works in this deployment.

    On Cloud Run the env var `GOOGLE_APPLICATION_CREDENTIALS` sometimes holds
    the raw service-account JSON (not a file path), and `firebase-admin-key`
    holds the same JSON under a different name. Default ADC blows up when it
    tries to open the JSON as a file — and the resulting exception message
    embeds the raw JSON (including the private key). This function never lets
    an underlying exception propagate with credential content in it; any
    failure surfaces as a sanitized _CredentialError.
    """
    from google.cloud import storage
    from google.oauth2 import service_account

    for var in ("GOOGLE_APPLICATION_CREDENTIALS", "firebase-admin-key"):
        raw = os.environ.get(var, "")
        if not raw:
            continue
        # If it's an existing file path, let ADC load it.
        if os.path.isfile(raw):
            try:
                return storage.Client()
            except Exception:
                # Don't log or re-raise with content — raise a sanitized error.
                logger.error("storage.Client() failed reading credentials file")
                raise _CredentialError("storage.Client init failed (file-path credentials)")
        # Otherwise try to parse as inline JSON content.
        if raw.lstrip().startswith("{"):
            try:
                info = json.loads(raw)
            except Exception:
                logger.error("Failed to json.loads credentials env var %s", var)
                raise _CredentialError(f"Credentials env var {var} is not valid JSON")
            try:
                creds = service_account.Credentials.from_service_account_info(info)
            except Exception:
                logger.error("from_service_account_info rejected credentials in %s", var)
                raise _CredentialError(f"Credentials env var {var} is not a valid service-account JSON")
            project = info.get("project_id")
            try:
                return storage.Client(project=project, credentials=creds)
            except Exception:
                logger.error("storage.Client() failed with explicit service-account credentials")
                raise _CredentialError("storage.Client init failed (inline credentials)")

    # Last resort: metadata-server ADC. If this fails, scrub the exception so
    # no env-var content can leak into the caller's logs or HTTP response.
    try:
        return storage.Client()
    except Exception:
        logger.error("storage.Client() ADC fallback failed")
        raise _CredentialError("storage.Client init failed (ADC fallback)")

INVOICE_BUCKET = "vouchervision-cop90-rasters"
INVOICE_PREFIX = "invoices/"

# Model identifiers normalized to a single canonical form. Order matters:
# longer / more specific names are tried first so "gemini 3.1 flash lite"
# wins over "gemini 3" etc.
_MODEL_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("gemini-3.1-flash-lite", re.compile(r"gemini\s*3\.1\s*flash\s*lite", re.I)),
    ("gemini-3-pro",          re.compile(r"gemini\s*3\s*pro", re.I)),
    ("gemini-3-flash",        re.compile(r"gemini\s*3\s*flash", re.I)),
    ("gemini-3",              re.compile(r"gemini\s*3(?!\.|\s*\d)", re.I)),
    ("gemini-2.5-pro",        re.compile(r"gemini\s*2\.5\s*pro", re.I)),
    ("gemini-2.5-flash",      re.compile(r"gemini\s*2\.5\s*flash", re.I)),
    ("gemini-2.0-flash",      re.compile(r"gemini\s*2\.0\s*flash", re.I)),
    ("gemini-mm-embedding",   re.compile(r"gemini\s*mm\s*embedding", re.I)),
]

# Maps Firestore llm_info keys (as written by update_usage_statistics) onto
# the canonical model names above so we can align counts with invoice SKUs.
FIRESTORE_MODEL_ALIASES: dict[str, str] = {
    "gemini-3-pro-preview": "gemini-3-pro",
    "gemini-3-pro-preview-short": "gemini-3-pro",
    "gemini-3-flash-preview": "gemini-3-flash",
    "gemini-3.1-flash-lite-preview": "gemini-3.1-flash-lite",
}

# Token-direction classification from SKU description.
_DIRECTION_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("cached",      re.compile(r"cached", re.I)),
    ("image_input", re.compile(r"image\s+input", re.I)),
    ("output",      re.compile(r"output\s+token", re.I)),
    ("input",       re.compile(r"input\s+token", re.I)),
    ("embedding",   re.compile(r"embedding", re.I)),
    ("search",      re.compile(r"search\s+query|queries\s+with\s+search", re.I)),
]


def normalize_firestore_model(name: str | None) -> str | None:
    """Canonicalize a Firestore llm_info key to match invoice SKU extraction."""
    if not name:
        return None
    if name in FIRESTORE_MODEL_ALIASES:
        return FIRESTORE_MODEL_ALIASES[name]
    lowered = name.lower().strip()
    for canonical, pattern in _MODEL_PATTERNS:
        if pattern.search(lowered):
            return canonical
    return lowered


def extract_model_from_sku(sku_description: str) -> str | None:
    for canonical, pattern in _MODEL_PATTERNS:
        if pattern.search(sku_description):
            return canonical
    return None


def extract_token_direction(sku_description: str) -> str | None:
    for label, pattern in _DIRECTION_PATTERNS:
        if pattern.search(sku_description):
            return label
    return None


_LLM_SERVICES = {"Gemini API", "Vertex AI"}

# SKUs on the LLM services that don't mention "gemini" but are still LLM
# inference charges (tools used by Gemini during generation).
_LLM_SERVICE_EXTRA_PATTERNS = (
    re.compile(r"llm\s+grounding", re.I),          # Vertex AI: search grounding
    re.compile(r"grounding\s+with\s+(google|search)", re.I),
    re.compile(r"search\s+tool", re.I),
)


def classify_sku(service_description: str, sku_description: str) -> str:
    """Return 'llm' if this is Gemini inference (incl. tool-use), else 'overhead'."""
    if service_description in _LLM_SERVICES:
        if extract_model_from_sku(sku_description):
            return "llm"
        for pat in _LLM_SERVICE_EXTRA_PATTERNS:
            if pat.search(sku_description):
                return "llm"
    return "overhead"


def _to_float(s: str) -> float:
    if s is None:
        return 0.0
    s = s.strip().replace(",", "").replace("$", "")
    if not s:
        return 0.0
    try:
        return float(s)
    except ValueError:
        return 0.0


def _parse_date(s: str) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.strptime(s.strip(), "%Y-%m-%d")
    except ValueError:
        return None


def parse_invoice_csv(source) -> dict:
    """Parse a GCP billing CSV.

    `source` may be bytes, str, a file-like object, or a path. Returns a dict
    with the invoice metadata and a classified list of line items.
    """
    if hasattr(source, "read"):
        data = source.read()
    else:
        with open(source, "rb") as f:
            data = f.read()
    if isinstance(data, bytes):
        text = data.decode("utf-8-sig", errors="replace")
    else:
        text = data

    lines = text.splitlines()
    invoice_date: datetime | None = None
    invoice_number = ""
    header_idx = -1
    for i, line in enumerate(lines):
        if line.startswith("Invoice number"):
            invoice_number = line.split(",", 1)[1].strip(" ,") if "," in line else ""
        elif line.startswith("Invoice date"):
            parts = line.split(",")
            if len(parts) >= 2:
                invoice_date = _parse_date(parts[1])
        elif line.startswith("Billing account name"):
            header_idx = i
            break

    if header_idx < 0:
        raise ValueError("Could not locate header row in invoice CSV")
    if invoice_date is None:
        raise ValueError("Could not locate 'Invoice date' in invoice preamble")

    reader = csv.DictReader(lines[header_idx:])
    billing_period = invoice_date.strftime("%Y-%m")

    line_items: list[dict] = []
    reported_total: float | None = None

    for row in reader:
        billing_name = (row.get("Billing account name") or "").strip()
        sku_desc = (row.get("SKU description") or "").strip()
        cost_type = (row.get("Cost type") or "").strip()

        # Trailing summary rows have empty billing name; capture Total for reconciliation.
        if not billing_name:
            if cost_type.lower() == "total":
                reported_total = _to_float(row.get("Cost ($)") or "0")
            continue
        if not sku_desc:
            continue

        service = (row.get("Service description") or "").strip()
        cost = _to_float(row.get("Cost ($)") or "0")
        unrounded = _to_float(row.get("Unrounded Cost ($)") or "0")
        usage_amount = _to_float(row.get("Usage amount") or "0")

        category = classify_sku(service, sku_desc)
        model = extract_model_from_sku(sku_desc) if category == "llm" else None
        direction = extract_token_direction(sku_desc) if category == "llm" else None
        # LLM SKUs without a model are tool-use charges (search grounding,
        # etc.) — not an "unclassified" warning.
        is_tool = (category == "llm") and (model is None)

        line_items.append({
            "service_description": service,
            "sku_description": sku_desc,
            "sku_id": (row.get("SKU ID") or "").strip(),
            "usage_amount": usage_amount,
            "usage_unit": (row.get("Usage unit") or "").strip(),
            "cost_usd": cost,
            "unrounded_cost_usd": unrounded,
            "usage_start": (row.get("Usage start date") or "").strip(),
            "usage_end": (row.get("Usage end date") or "").strip(),
            "category": category,
            "model": model,
            "direction": direction,
            "is_tool": is_tool,
        })

    total_llm = sum(li["unrounded_cost_usd"] for li in line_items if li["category"] == "llm")
    total_overhead = sum(li["unrounded_cost_usd"] for li in line_items if li["category"] == "overhead")
    total_cost = total_llm + total_overhead

    return {
        "invoice_number": invoice_number,
        "invoice_date": invoice_date.strftime("%Y-%m-%d"),
        "billing_period": billing_period,
        "line_items": line_items,
        "total_cost": round(total_cost, 2),
        "total_llm_cost": round(total_llm, 2),
        "total_overhead_cost": round(total_overhead, 2),
        "reported_total": reported_total,
    }


def list_invoices(storage_client, bucket_name: str = INVOICE_BUCKET,
                  prefix: str = INVOICE_PREFIX) -> list:
    """List CSV blobs under the invoices/ prefix. Sorted by name."""
    bucket = storage_client.bucket(bucket_name)
    blobs = [b for b in bucket.list_blobs(prefix=prefix)
             if b.name.lower().endswith(".csv")]
    blobs.sort(key=lambda b: b.name)
    return blobs


def _safe_ratio(num: float, denom: float) -> float:
    return (num / denom) if denom else 0.0


def _format_user_model_mix(llm_info: dict) -> dict[str, float]:
    """Collapse Firestore llm_info into canonical-model → fraction."""
    canonical_counts: dict[str, int] = defaultdict(int)
    for name, cnt in (llm_info or {}).items():
        if not name or name.startswith("failure_code_"):
            continue
        c = normalize_firestore_model(name)
        if c:
            canonical_counts[c] += int(cnt or 0)
    total = sum(canonical_counts.values())
    if not total:
        return {}
    return {k: v / total for k, v in canonical_counts.items()}


def build_monthly_cost_report(invoices: list[dict],
                              firestore_usage: list[dict]) -> dict:
    """Merge parsed invoices with Firestore usage_statistics into a report.

    `firestore_usage` is a list of `usage_statistics` documents as dicts.
    Each invoice entry comes from `parse_invoice_csv`.
    """
    months: list[str] = sorted({inv["billing_period"] for inv in invoices})
    per_month: dict[str, dict] = {}

    # Precompute per-user info we re-use across months.
    users = []
    for doc in firestore_usage:
        email = doc.get("user_email")
        if not email:
            continue
        total_imgs = int(doc.get("total_images_processed") or 0)
        total_tokens = int(doc.get("total_tokens_all") or 0)
        monthly = {k: int(v or 0) for k, v in (doc.get("monthly_usage") or {}).items()}
        daily = {k: int(v or 0) for k, v in (doc.get("daily_usage") or {}).items()}
        mix = _format_user_model_mix(doc.get("llm_info") or {})
        users.append({
            "email": email,
            "total_images": total_imgs,
            "total_tokens": total_tokens,
            "tokens_per_image": _safe_ratio(total_tokens, total_imgs),
            "monthly": monthly,
            "daily": daily,
            "model_mix": mix,
        })

    # Aggregate: total spend & specimens for each month.
    for month in months:
        month_invoices = [inv for inv in invoices if inv["billing_period"] == month]

        per_model_cost: dict[str, float] = defaultdict(float)
        per_model_tokens: dict[str, int] = defaultdict(int)
        per_model_direction_cost: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
        overhead_breakdown: dict[str, float] = defaultdict(float)
        tool_cost: dict[str, float] = defaultdict(float)
        unclassified: list[dict] = []

        total_cost = 0.0
        total_llm = 0.0
        total_overhead = 0.0

        for inv in month_invoices:
            for li in inv["line_items"]:
                total_cost += li["unrounded_cost_usd"]
                if li["category"] == "llm":
                    total_llm += li["unrounded_cost_usd"]
                    if li["model"]:
                        per_model_cost[li["model"]] += li["unrounded_cost_usd"]
                        # Only token-count SKUs (usage_unit="count") should feed token totals.
                        if li["usage_unit"] == "count":
                            per_model_tokens[li["model"]] += int(li["usage_amount"])
                        if li["direction"]:
                            per_model_direction_cost[li["model"]][li["direction"]] += li["unrounded_cost_usd"]
                    elif li.get("is_tool"):
                        tool_cost[li["sku_description"]] += li["unrounded_cost_usd"]
                    else:
                        unclassified.append({"sku": li["sku_description"], "cost": li["unrounded_cost_usd"]})
                else:
                    total_overhead += li["unrounded_cost_usd"]
                    overhead_breakdown[li["sku_description"]] += li["unrounded_cost_usd"]

        # Total specimens processed that month (across all users).
        total_specimens = sum(u["monthly"].get(month, 0) for u in users)

        cost_per_specimen = {
            "llm": _safe_ratio(total_llm, total_specimens),
            "overhead": _safe_ratio(total_overhead, total_specimens),
            "total": _safe_ratio(total_llm + total_overhead, total_specimens),
        }

        # Per-user apportionment: share of month's specimens, weighted by model mix.
        # Step 1: compute each user's model-weighted specimen share per model.
        model_specimen_totals: dict[str, float] = defaultdict(float)
        user_weighted: list[dict] = []
        for u in users:
            user_specimens = u["monthly"].get(month, 0)
            if user_specimens <= 0:
                continue
            # If the user has no llm_info (shouldn't happen often), fall back to
            # overall month's model-cost distribution.
            mix = u["model_mix"] or {m: _safe_ratio(c, sum(per_model_cost.values()))
                                     for m, c in per_model_cost.items()}
            weighted = {m: user_specimens * frac for m, frac in mix.items()}
            for m, w in weighted.items():
                model_specimen_totals[m] += w
            user_weighted.append({"user": u, "specimens": user_specimens, "weighted": weighted})

        # Orphan LLM cost: models that appear in the invoice this month but
        # nobody in user_weighted has them in their mix. Distribute pro-rata
        # by specimen count so nothing gets dropped.
        orphan_model_cost = sum(
            cost for m, cost in per_model_cost.items()
            if model_specimen_totals.get(m, 0.0) == 0
        )

        per_user_rows: list[dict] = []
        for uw in user_weighted:
            u = uw["user"]
            specimens = uw["specimens"]
            est_llm_cost = 0.0
            for m, w in uw["weighted"].items():
                denom = model_specimen_totals.get(m, 0.0)
                if denom > 0:
                    est_llm_cost += per_model_cost.get(m, 0.0) * (w / denom)
            # Pro-rate orphan LLM costs by specimen share.
            if orphan_model_cost and total_specimens:
                est_llm_cost += orphan_model_cost * (specimens / total_specimens)
            # Overhead prorated by raw specimen share.
            est_overhead = (_safe_ratio(specimens, total_specimens) * total_overhead) if total_specimens else 0.0
            est_total = est_llm_cost + est_overhead
            top_model = max(u["model_mix"].items(), key=lambda kv: kv[1])[0] if u["model_mix"] else None
            per_user_rows.append({
                "email": u["email"],
                "specimens": specimens,
                "est_llm_cost": round(est_llm_cost, 4),
                "est_overhead_cost": round(est_overhead, 4),
                "est_total_cost": round(est_total, 4),
                "cost_per_specimen": round(_safe_ratio(est_total, specimens), 6),
                "top_model": top_model,
                "model_mix": {k: round(v, 4) for k, v in u["model_mix"].items()},
            })
        per_user_rows.sort(key=lambda r: r["est_total_cost"], reverse=True)

        # Daily token reconstruction (scaled so the month sums to invoice tokens).
        invoice_tokens_month = sum(per_model_tokens.values())
        raw_daily_by_date: dict[str, dict[str, float]] = defaultdict(dict)  # date -> {email: est tokens}
        est_month_tokens = 0.0
        for u in users:
            if not u["daily"] or u["tokens_per_image"] <= 0:
                continue
            for date, imgs in u["daily"].items():
                if not date.startswith(month):
                    continue
                est = imgs * u["tokens_per_image"]
                raw_daily_by_date[date][u["email"]] = est
                est_month_tokens += est
        scale = _safe_ratio(invoice_tokens_month, est_month_tokens) if est_month_tokens else 1.0
        daily_tokens_by_date = {
            date: {email: round(tokens * scale) for email, tokens in per_user.items()}
            for date, per_user in raw_daily_by_date.items()
        }

        per_model_summary = {}
        for m, cost in per_model_cost.items():
            tokens = per_model_tokens.get(m, 0)
            directions = dict(per_model_direction_cost.get(m, {}))
            per_model_summary[m] = {
                "cost": round(cost, 2),
                "tokens": tokens,
                "rate_per_mtok": round(cost / (tokens / 1_000_000), 4) if tokens else None,
                "direction_cost": {d: round(v, 4) for d, v in directions.items()},
            }

        per_month[month] = {
            "total_cost": round(total_cost, 2),
            "llm_cost": round(total_llm, 2),
            "overhead_cost": round(total_overhead, 2),
            "total_specimens": total_specimens,
            "cost_per_specimen": {k: round(v, 6) for k, v in cost_per_specimen.items()},
            "per_model": per_model_summary,
            "per_user_top20": per_user_rows[:20],
            "per_user_count": len(per_user_rows),
            "overhead_breakdown": sorted(
                [{"sku": sku, "cost": round(c, 4)} for sku, c in overhead_breakdown.items()],
                key=lambda r: r["cost"], reverse=True,
            ),
            "tool_breakdown": sorted(
                [{"sku": sku, "cost": round(c, 4)} for sku, c in tool_cost.items()],
                key=lambda r: r["cost"], reverse=True,
            ),
            "unclassified_skus": unclassified,
            "daily_tokens_by_date": daily_tokens_by_date,
            "invoice_tokens_total": invoice_tokens_month,
        }

    # All-time rollup.
    all_total_cost = sum(m["total_cost"] for m in per_month.values())
    all_total_llm = sum(m["llm_cost"] for m in per_month.values())
    all_total_overhead = sum(m["overhead_cost"] for m in per_month.values())
    all_total_specimens = sum(m["total_specimens"] for m in per_month.values())

    # All-time model rates: cost-weighted average across months.
    model_rate_num: dict[str, float] = defaultdict(float)
    model_rate_den: dict[str, int] = defaultdict(int)
    for m in per_month.values():
        for model, info in m["per_model"].items():
            if info["tokens"]:
                model_rate_num[model] += info["cost"]
                model_rate_den[model] += info["tokens"]
    all_time_rates = {
        model: {
            "cost": round(model_rate_num[model], 2),
            "tokens": model_rate_den[model],
            "rate_per_mtok": round(model_rate_num[model] / (model_rate_den[model] / 1_000_000), 4),
        }
        for model in model_rate_num
    }

    return {
        "months": months,
        "per_month": per_month,
        "all_time": {
            "total_cost": round(all_total_cost, 2),
            "llm_cost": round(all_total_llm, 2),
            "overhead_cost": round(all_total_overhead, 2),
            "total_specimens": all_total_specimens,
            "cost_per_specimen": {
                "llm": round(_safe_ratio(all_total_llm, all_total_specimens), 6),
                "overhead": round(_safe_ratio(all_total_overhead, all_total_specimens), 6),
                "total": round(_safe_ratio(all_total_cost, all_total_specimens), 6),
            },
            "model_rates": all_time_rates,
            "break_even_price_per_specimen": round(_safe_ratio(all_total_cost, all_total_specimens), 6),
        },
    }


# ---------------------------------------------------------------------------
# Simple TTL cache keyed by the set of blob etags (invalidates when CSVs change).
# ---------------------------------------------------------------------------
_CACHE_LOCK = threading.Lock()
_CACHE: dict = {"key": None, "value": None, "ts": 0.0}
_CACHE_TTL_SECONDS = 60.0


def load_report_from_gcs(storage_client, firestore_usage: list[dict]) -> dict:
    """Fetch invoices from GCS, parse, merge with Firestore, return the report.

    Cached for ~60s by the concatenation of blob etags + a count-based hash of
    firestore_usage so repeated tab clicks don't re-read everything.
    """
    import time
    blobs = list_invoices(storage_client)
    etag_key = "|".join(b.etag or b.name for b in blobs)
    fu_sig = f"{len(firestore_usage)}:{sum(int(d.get('total_images_processed') or 0) for d in firestore_usage)}"
    cache_key = f"{etag_key}::{fu_sig}"

    with _CACHE_LOCK:
        if (_CACHE["key"] == cache_key
                and (time.time() - _CACHE["ts"]) < _CACHE_TTL_SECONDS
                and _CACHE["value"] is not None):
            return _CACHE["value"]

    invoices: list[dict] = []
    for blob in blobs:
        try:
            raw = blob.download_as_bytes()
            invoices.append(parse_invoice_csv(io.BytesIO(raw)))
        except Exception as e:
            logger.error("Failed to parse invoice %s: %s", blob.name, e)

    report = build_monthly_cost_report(invoices, firestore_usage)
    report["invoice_files"] = [
        {"name": b.name, "size": b.size, "updated": str(b.updated)} for b in blobs
    ]

    with _CACHE_LOCK:
        _CACHE["key"] = cache_key
        _CACHE["value"] = report
        _CACHE["ts"] = time.time()
    return report


# ---------------------------------------------------------------------------
# CLI: python -m cost_analytics --audit <path-or-gs-prefix>
# ---------------------------------------------------------------------------
def _audit_cli(paths: list[str]) -> int:
    """Run classifier over local CSVs (or a directory) and print unclassified SKUs."""
    import glob, os
    files: list[str] = []
    for p in paths:
        if os.path.isdir(p):
            files.extend(sorted(glob.glob(os.path.join(p, "*.csv"))))
        else:
            files.extend(sorted(glob.glob(p)))
    if not files:
        print("No CSV files found.")
        return 1

    seen: dict[str, float] = defaultdict(float)
    unclassified: dict[str, float] = defaultdict(float)
    total = 0.0
    llm_total = 0.0
    for f in files:
        inv = parse_invoice_csv(f)
        total += inv["total_cost"]
        llm_total += inv["total_llm_cost"]
        for li in inv["line_items"]:
            seen[li["sku_description"]] += li["unrounded_cost_usd"]
            if li["category"] == "llm" and not li["model"] and not li.get("is_tool"):
                unclassified[li["sku_description"]] += li["unrounded_cost_usd"]
        print(f"{os.path.basename(f):80s} {inv['billing_period']} "
              f"total=${inv['total_cost']:>9.2f} llm=${inv['total_llm_cost']:>9.2f} "
              f"overhead=${inv['total_overhead_cost']:>9.2f} items={len(inv['line_items'])}")

    print(f"\nAcross all files: total=${total:.2f} llm=${llm_total:.2f}")
    if unclassified:
        print("\nLLM SKUs with no model extracted (extend _MODEL_PATTERNS):")
        for sku, cost in sorted(unclassified.items(), key=lambda kv: -kv[1]):
            print(f"  ${cost:>9.4f}  {sku}")
        return 2
    print("\nAll LLM SKUs resolved to a model.")
    return 0


if __name__ == "__main__":
    import sys
    args = sys.argv[1:]
    if args and args[0] == "--audit":
        sys.exit(_audit_cli(args[1:]))
    print("Usage: python -m cost_analytics --audit <csv-or-dir> [<csv-or-dir> ...]")
    sys.exit(1)

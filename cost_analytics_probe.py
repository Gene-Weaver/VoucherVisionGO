"""Ad-hoc cost-analysis probes.

Runs directly against local invoice CSVs (no server, no Firestore). Produces
month-level and per-model breakdowns, plus a "what's shrinkable" overhead
audit. Wired to the same classifier as cost_analytics.py so numbers match
the admin dashboard.

Usage:
    python cost_analytics_probe.py <dir-or-csv>...

Defaults to ~/Downloads/My\ Billing\ Account*.csv if no args are given.
"""
from __future__ import annotations

import glob
import os
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

# Use the same classifier as the production report so numbers agree.
from cost_analytics import parse_invoice_csv


def load_invoices(paths):
    files = []
    for p in paths:
        if os.path.isdir(p):
            files.extend(sorted(glob.glob(os.path.join(p, "*.csv"))))
        else:
            files.extend(sorted(glob.glob(p)))
    if not files:
        return {}
    out = {}
    for f in files:
        inv = parse_invoice_csv(f)
        out[inv["billing_period"]] = inv
    return out


def headline(invoices):
    months = sorted(invoices.keys())
    print("=" * 104)
    print(f"{'Month':<10} {'Total':>10} {'LLM':>10} {'Overhead':>10} {'LLM/Ovh':>10} {'LLM tokens':>18}")
    print("-" * 104)
    for mo in months:
        inv = invoices[mo]
        tokens = sum(li["usage_amount"] for li in inv["line_items"]
                     if li["category"] == "llm" and li["usage_unit"] == "count")
        ratio = (inv["total_llm_cost"] / inv["total_overhead_cost"]) if inv["total_overhead_cost"] else 0
        print(f"{mo:<10} ${inv['total_cost']:>9.2f} ${inv['total_llm_cost']:>9.2f} "
              f"${inv['total_overhead_cost']:>9.2f} {ratio:>9.2f}x {int(tokens):>18,d}")


def overhead_sku_matrix(invoices):
    months = sorted(invoices.keys())
    by_sku = defaultdict(lambda: defaultdict(float))
    for mo, inv in invoices.items():
        for li in inv["line_items"]:
            if li["category"] == "overhead":
                by_sku[li["sku_description"]][mo] += li["unrounded_cost_usd"]
    skus = sorted(by_sku, key=lambda s: -max(by_sku[s].get(mo, 0) for mo in months))

    print("\n" + "=" * 104)
    print("OVERHEAD SKU BREAKDOWN")
    print("=" * 104)
    header = f"{'SKU':<62}" + "".join(f"{mo:>11}" for mo in months)
    print(header)
    print("-" * len(header))
    for sku in skus:
        row = by_sku[sku]
        vals = [row.get(mo, 0) for mo in months]
        if max(vals) < 0.01:
            continue
        costs = "".join(f"  ${v:>8.2f}" for v in vals)
        print(f"{sku[:62]:<62}{costs}")


def cloud_run_detail(invoices):
    months = sorted(invoices.keys())
    print("\n" + "=" * 104)
    print("CLOUD RUN USAGE (per-request vs min-instance)")
    print("=" * 104)
    print(f"{'Month':<10} {'Req CPU-s':>14} {'Req Mem GiB-s':>16} {'Min CPU-s':>12} {'Min Mem GiB-s':>16} "
          f"{'Requests':>12} {'CR cost':>10}")
    for mo in months:
        inv = invoices[mo]
        req_cpu = req_mem = min_cpu = min_mem = reqs = cr_cost = 0.0
        for li in inv["line_items"]:
            sku = li["sku_description"]
            if sku == "Services CPU (Request-based billing)":
                req_cpu = li["usage_amount"]; cr_cost += li["unrounded_cost_usd"]
            elif sku == "Services Memory (Request-based billing)":
                req_mem = li["usage_amount"]; cr_cost += li["unrounded_cost_usd"]
            elif sku == "Services Min Instance CPU (Request-based billing)":
                min_cpu = li["usage_amount"]; cr_cost += li["unrounded_cost_usd"]
            elif sku == "Services Min Instance Memory (Request-based billing)":
                min_mem = li["usage_amount"]; cr_cost += li["unrounded_cost_usd"]
            elif sku == "Requests":
                reqs = li["usage_amount"]
        print(f"{mo:<10} {req_cpu:>14,.0f} {req_mem:>16,.0f} {min_cpu:>12,.0f} {min_mem:>16,.0f} "
              f"{int(reqs):>12,d} ${cr_cost:>9.2f}")

    print("\n" + "=" * 104)
    print("CLOUD RUN 'ACTIVE TIME' PER REQUEST")
    print("=" * 104)
    print(f"{'Month':<10} {'CPU-s/req':>12} {'Mem GiB-s/req':>16} {'$/Kreq':>12}")
    for mo in months:
        inv = invoices[mo]
        req_cpu = req_mem = reqs = cost = 0.0
        for li in inv["line_items"]:
            sku = li["sku_description"]
            if sku == "Services CPU (Request-based billing)":
                req_cpu = li["usage_amount"]; cost += li["unrounded_cost_usd"]
            elif sku == "Services Memory (Request-based billing)":
                req_mem = li["usage_amount"]; cost += li["unrounded_cost_usd"]
            elif sku == "Requests":
                reqs = li["usage_amount"]
        if reqs > 0:
            print(f"{mo:<10} {req_cpu/reqs:>12.2f} {req_mem/reqs:>16.2f} ${(cost/reqs)*1000:>10.4f}")


def per_model(invoices):
    """Per-model cost & blended $/Mtok across all months."""
    months = sorted(invoices.keys())
    model_cost = defaultdict(float)
    model_tokens = defaultdict(int)
    dir_cost = defaultdict(lambda: defaultdict(float))  # model -> direction -> $
    dir_tokens = defaultdict(lambda: defaultdict(int))

    for inv in invoices.values():
        for li in inv["line_items"]:
            if li["category"] != "llm" or not li["model"]:
                continue
            model_cost[li["model"]] += li["unrounded_cost_usd"]
            if li["usage_unit"] == "count":
                model_tokens[li["model"]] += int(li["usage_amount"])
                if li["direction"]:
                    dir_cost[li["model"]][li["direction"]] += li["unrounded_cost_usd"]
                    dir_tokens[li["model"]][li["direction"]] += int(li["usage_amount"])

    print("\n" + "=" * 104)
    print("PER-MODEL COST (all months combined)")
    print("=" * 104)
    print(f"{'Model':<26} {'Total $':>10} {'Tokens':>16} {'$/Mtok':>10}  directions")
    print("-" * 104)
    for model in sorted(model_cost, key=lambda m: -model_cost[m]):
        cost = model_cost[model]
        tokens = model_tokens[model]
        rate = (cost / (tokens / 1_000_000)) if tokens else 0.0
        dirs = dir_cost[model]
        dir_str = ", ".join(f"{d}=${dirs[d]:.2f}" for d in sorted(dirs, key=lambda d: -dirs[d]))
        print(f"{model:<26} ${cost:>9.2f} {tokens:>16,d} ${rate:>9.4f}  {dir_str}")

    return model_cost, model_tokens, dir_cost, dir_tokens


def per_model_unit_economics(invoices, monthly_specimens: dict[str, int]):
    """For each model, estimate cost per specimen and overhead %."""
    months = sorted(invoices.keys())
    print("\n" + "=" * 104)
    print("PER-MODEL UNIT ECONOMICS (all-time blended)")
    print("  Assumes a 'representative specimen' uses a typical input+output token mix.")
    print("=" * 104)

    # Compute all-time per-model rates.
    model_cost = defaultdict(float)
    model_tokens = defaultdict(int)
    input_cost = defaultdict(float); input_tokens = defaultdict(int)
    output_cost = defaultdict(float); output_tokens = defaultdict(int)
    cached_cost = defaultdict(float); cached_tokens = defaultdict(int)
    image_cost = defaultdict(float); image_tokens = defaultdict(int)

    for inv in invoices.values():
        for li in inv["line_items"]:
            if li["category"] != "llm" or not li["model"] or li["usage_unit"] != "count":
                continue
            m = li["model"]
            c, t = li["unrounded_cost_usd"], int(li["usage_amount"])
            model_cost[m] += c; model_tokens[m] += t
            d = li["direction"]
            if d == "output":
                output_cost[m] += c; output_tokens[m] += t
            elif d == "input":
                input_cost[m] += c; input_tokens[m] += t
            elif d == "cached":
                cached_cost[m] += c; cached_tokens[m] += t
            elif d == "image_input":
                image_cost[m] += c; image_tokens[m] += t

    # All-time overhead per specimen.
    total_overhead = sum(inv["total_overhead_cost"] for inv in invoices.values())
    total_specimens = sum(monthly_specimens.values())
    overhead_per_specimen = total_overhead / total_specimens if total_specimens else 0.0

    print(f"All-time overhead: ${total_overhead:.2f}   specimens (given): {total_specimens:,}")
    print(f"Overhead $/specimen (amortized): ${overhead_per_specimen:.6f}")
    print()
    print(f"{'Model':<26} {'$/Mtok in':>11} {'$/Mtok out':>11} {'$/Mtok cache':>14} {'$/spec@5k':>12}"
          f" {'$/spec@20k':>12} {'Ovh%@5k':>10} {'Ovh%@20k':>10}")
    print("-" * 130)

    def rate(cost, tokens): return (cost / (tokens / 1_000_000)) if tokens else 0.0

    # For a "representative specimen" assume: 30% input text, 60% output text,
    # 10% image input, no cached. This matches VoucherVision OCR+LLM-parse
    # workloads roughly.
    def per_spec_llm(m, total_tokens):
        r_in = rate(input_cost[m], input_tokens[m])
        r_out = rate(output_cost[m], output_tokens[m])
        r_img = rate(image_cost[m], image_tokens[m])
        # Fallback to blended rate if direction is missing.
        blended = rate(model_cost[m], model_tokens[m])
        r_in = r_in or blended
        r_out = r_out or blended
        r_img = r_img or blended
        return (0.30 * r_in + 0.60 * r_out + 0.10 * r_img) * (total_tokens / 1_000_000)

    for m in sorted(model_cost, key=lambda m: -model_cost[m]):
        r_in = rate(input_cost[m], input_tokens[m])
        r_out = rate(output_cost[m], output_tokens[m])
        r_cached = rate(cached_cost[m], cached_tokens[m])
        spec_5k = per_spec_llm(m, 5_000)
        spec_20k = per_spec_llm(m, 20_000)
        ovh_pct_5k = overhead_per_specimen / (spec_5k + overhead_per_specimen) * 100 if (spec_5k + overhead_per_specimen) else 0
        ovh_pct_20k = overhead_per_specimen / (spec_20k + overhead_per_specimen) * 100 if (spec_20k + overhead_per_specimen) else 0
        print(f"{m:<26} ${r_in:>10.4f} ${r_out:>10.4f} ${r_cached:>13.4f} ${spec_5k:>11.5f}"
              f" ${spec_20k:>11.5f} {ovh_pct_5k:>9.1f}% {ovh_pct_20k:>9.1f}%")

    print()
    print("  $/spec@5k  = est. LLM $/specimen assuming 5,000 tokens (30% in / 60% out / 10% image).")
    print("  $/spec@20k = same, with 20,000 tokens (heavier context, longer outputs).")
    print("  Ovh%@N     = overhead $/specimen as % of (LLM + overhead). High means overhead dominates.")


def shrinkable_overhead(invoices):
    """Classify overhead SKUs as fixed / variable / prunable with a commentary."""
    months = sorted(invoices.keys())
    total_overhead = sum(inv["total_overhead_cost"] for inv in invoices.values())
    by_sku = defaultdict(lambda: defaultdict(float))
    for mo, inv in invoices.items():
        for li in inv["line_items"]:
            if li["category"] == "overhead":
                by_sku[li["sku_description"]][mo] += li["unrounded_cost_usd"]

    # Tag each SKU with a shrink category + rationale.
    rules = [
        # (substring match, tag, advice)
        ("Cloud Load Balancer Forwarding Rule", "FIXED",
         "$0.025/hr. Required only if you use the HTTPS Load Balancer. Alternative: expose Cloud Run directly (no LB) — saves ~$18/mo but loses Cloud Armor protection."),
        ("Static Ip Charge", "FIXED",
         "$0.01/hr. Needed only because the LB has a reserved static IP. Removing the LB removes this too (~$7/mo)."),
        ("Networking Cloud Armor Policy", "FIXED",
         "$5/mo for WAF rules. Keep if you need DDoS/bot protection; remove if Cloud Run invoker auth is sufficient."),
        ("Networking Cloud Armor Rule", "FIXED",
         "$1/rule/mo. Currently 2 rules = $2/mo. Prune unused rules."),
        ("Artifact Registry Storage", "PRUNABLE",
         "Grows monotonically as Docker image versions accumulate. Run `gcloud artifacts docker images list` + `delete` on old Cloud Run revisions' images. Typical saving: 40-70% ($7-12/mo here)."),
        ("Services CPU (Request-based billing)", "VARIABLE",
         "Proportional to request-active CPU time. Shrink by choosing faster models, trimming prompt length, and avoiding retries."),
        ("Services Memory (Request-based billing)", "VARIABLE",
         "Proportional to request-active memory. Shrink by lowering the Cloud Run memory allocation if headroom allows."),
        ("Min Instance", "IDLE TAX",
         "Only billed when min-instances > 0. Setting min-instances=0 eliminates this (at the cost of cold-start latency)."),
        ("Secret version replica storage", "FIXED",
         "$0.04/month/version per replica region. Delete unused secret versions; cap replica regions."),
        ("Secret access operations", "VARIABLE",
         "Tiny ($0.03/10k accesses). Shrink by caching secrets in-process at startup."),
        ("Cloud Run Network Internet Data Transfer", "VARIABLE",
         "Egress to internet. Shrink by compressing responses, avoiding large payloads in responses."),
        ("Artifact Registry Network", "VARIABLE",
         "Usually tiny unless you pull images across regions. Keep Cloud Run and AR in same region."),
        ("Cloud CDN", "VARIABLE",
         "Only relevant if you serve cacheable static assets. Tiny here."),
        ("Cloud Firestore", "VARIABLE",
         "Reads/writes + storage. Shrink with batching and indexes that avoid table scans."),
        ("Cloud Storage", "VARIABLE",
         "Bucket storage + ops. Shrink by lifecycling old uploads and using Nearline/Coldline for archives."),
        ("Cloud Logging", "VARIABLE",
         "$0.50/GiB after the 50 GiB free tier. Shrink with log-level filtering + exclusion filters."),
        ("Compute Engine", "VARIABLE",
         "Static-IP comes from Compute Engine SKU. Same as Static IP row above."),
        ("Identity Platform", "FIXED",
         "MAU-based pricing. $0 in free tier."),
        ("Cloud Build", "VARIABLE",
         "Build minutes for CI. Shrink with caching, smaller base images, less frequent deploys."),
        ("Cloud Vision API", "VARIABLE",
         "Per-operation. $0 here so likely in the free tier."),
    ]

    print("\n" + "=" * 104)
    print("WHAT'S SHRINKABLE IN OVERHEAD — ranked by current cost")
    print("=" * 104)
    total_by_sku = {sku: sum(m.values()) for sku, m in by_sku.items()}
    rows = sorted(total_by_sku.items(), key=lambda kv: -kv[1])
    printed = 0
    for sku, total in rows:
        if total < 0.01:
            continue
        tag = "?"; advice = "(no rule matched — consider adding one)"
        for pat, t, a in rules:
            if pat in sku:
                tag, advice = t, a; break
        share = total / total_overhead * 100 if total_overhead else 0
        print(f"  ${total:>7.2f}  ({share:>5.2f}% of overhead)  [{tag:<9s}]  {sku[:70]}")
        print(f"           → {advice}")
        printed += 1
    print(f"\nTotal overhead across {len(months)} months: ${total_overhead:.2f}")
    print("Tags: FIXED = baseline service charge, billed per calendar time, mostly independent of traffic.")
    print("      VARIABLE = scales with workload; shrink by optimizing request characteristics.")
    print("      PRUNABLE = one-time cleanup (old artifacts/secrets/logs) will reduce this.")
    print("      IDLE TAX = only appears when min-instances > 0.")


def requests_per_month(invoices):
    """Use Cloud Run 'Requests' SKU as a specimen proxy (1 specimen ≈ 1 request)."""
    out = {}
    for mo, inv in invoices.items():
        n = 0
        for li in inv["line_items"]:
            if li["sku_description"] == "Requests":
                n = int(li["usage_amount"])
                break
        out[mo] = n
    return out


def main():
    argv = sys.argv[1:]
    if not argv:
        argv = [os.path.expanduser("~/Downloads")]
    invoices = load_invoices(argv)
    if not invoices:
        print("No invoices found.")
        sys.exit(1)

    headline(invoices)
    overhead_sku_matrix(invoices)
    cloud_run_detail(invoices)
    per_model(invoices)

    # Proxy for specimen count: Cloud Run request count. Each /process_image
    # invocation ≈ 1 request ≈ 1 specimen. Health-check noise is minor.
    specimens = requests_per_month(invoices)
    print(f"\nUsing Cloud Run request count as specimen-count proxy: {specimens}")
    per_model_unit_economics(invoices, specimens)

    shrinkable_overhead(invoices)


if __name__ == "__main__":
    main()

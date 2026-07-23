#!/usr/bin/env python3
"""
export_all_keywords.py — Count and download ALL keyword entries from Supabase.

Connects to the articles table, prints summary stats (total rows,
category breakdown, definition length stats), and exports everything
to a CSV so you can decide on local vs Snowflake Cortex processing.

Usage:
    python export_all_keywords.py
    python export_all_keywords.py --output all_keywords.csv
"""

import argparse
import csv
import json
import os
import sys
import urllib.error
import urllib.request
from collections import Counter
from pathlib import Path

# ---------------------------------------------------------------------------
# .env loader (same pattern as sample_for_review.py)
# ---------------------------------------------------------------------------

def load_dotenv():
    for p in [Path(__file__).parent / ".env", Path.cwd() / ".env"]:
        if p.exists():
            with open(p, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    key, _, value = line.partition("=")
                    key = key.strip()
                    value = value.strip().strip('"').strip("'")
                    if key and key not in os.environ:
                        os.environ[key] = value
            return

load_dotenv()

SUPABASE_URL = os.getenv("NEXT_PUBLIC_SUPABASE_URL", "").rstrip("/")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
TABLE        = "articles"

if not SUPABASE_URL or not SUPABASE_KEY:
    print("ERROR: Missing NEXT_PUBLIC_SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY in .env",
          file=sys.stderr)
    sys.exit(1)

HEADERS = {
    "apikey":        SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type":  "application/json",
}

# ---------------------------------------------------------------------------
# Fetch helpers
# ---------------------------------------------------------------------------

def fetch_all(url: str) -> list[dict]:
    """Fetch all pages from a PostgREST endpoint (handles 1000-row limit)."""
    results = []
    offset  = 0
    limit   = 1000
    while True:
        paged = f"{url}&limit={limit}&offset={offset}"
        req   = urllib.request.Request(paged, headers={**HEADERS, "Prefer": "count=none"})
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                batch = json.loads(resp.read())
                results.extend(batch)
                if len(batch) < limit:
                    break
                offset += limit
        except urllib.error.HTTPError as e:
            print(f"HTTP {e.code}: {e.read().decode()[:200]}", file=sys.stderr)
            sys.exit(1)
    return results

# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------

def print_stats(rows: list[dict]):
    """Print summary statistics about the dataset."""
    total = len(rows)

    print("=" * 60)
    print(f"  TOTAL ROWS: {total}")
    print("=" * 60)

    # --- Category breakdown ---
    cats = Counter(r.get("category") or "Unknown" for r in rows)
    print(f"\n  CATEGORIES: {len(cats)} unique")
    print(f"  {'Category':<40} {'Count':>6} {'%':>7}")
    print(f"  {'-'*40} {'-'*6} {'-'*7}")
    for cat, count in sorted(cats.items(), key=lambda x: -x[1]):
        print(f"  {cat:<40} {count:>6} {count/total*100:>6.1f}%")

    # --- Definition length stats ---
    def_lengths = [len(r.get("definition") or "") for r in rows]
    avg_len = sum(def_lengths) / total if total else 0
    max_len = max(def_lengths) if def_lengths else 0
    min_len = min(def_lengths) if def_lengths else 0
    empty   = sum(1 for d in def_lengths if d == 0)

    print(f"\n  DEFINITION LENGTHS:")
    print(f"    Average : {avg_len:.0f} chars")
    print(f"    Min     : {min_len} chars")
    print(f"    Max     : {max_len} chars")
    print(f"    Empty   : {empty} definitions")

    # --- Token estimate (rough: 1 token ≈ 4 chars) ---
    total_chars = sum(def_lengths)
    est_tokens  = total_chars // 4
    print(f"\n  TOKEN ESTIMATE (definitions only):")
    print(f"    Total chars  : {total_chars:,}")
    print(f"    Est. tokens  : {est_tokens:,} (approx, at ~4 chars/token)")
    print(f"    Per row avg  : {est_tokens // total if total else 0} tokens")

    # --- Slug uniqueness check ---
    slugs = [r.get("slug", "") for r in rows]
    dupes = total - len(set(slugs))
    if dupes:
        print(f"\n  WARNING: {dupes} duplicate slugs found!")
    else:
        print(f"\n  All slugs are unique.")

    print("=" * 60)

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def parse_args():
    p = argparse.ArgumentParser(description="Export all keywords from Supabase.")
    p.add_argument("--output", default="all_keywords.csv",
                   help="Output CSV filename (default: all_keywords.csv)")
    return p.parse_args()


def main():
    args = parse_args()

    # Fetch everything
    print(f"Fetching all entries from Supabase ({TABLE})...")
    url  = f"{SUPABASE_URL}/rest/v1/{TABLE}?select=slug,term,category,definition"
    rows = fetch_all(url)

    if not rows:
        print("ERROR: No rows returned from Supabase.", file=sys.stderr)
        sys.exit(1)

    # Print stats
    print_stats(rows)

    # Write full CSV
    out_path = Path(__file__).parent / args.output
    with open(out_path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["slug", "term", "category", "definition"])
        for row in rows:
            writer.writerow([
                row.get("slug", ""),
                row.get("term", ""),
                row.get("category", ""),
                row.get("definition", ""),
            ])

    print(f"\nFull export written → {out_path}")
    print(f"\nNext steps:")
    print(f"  1. Open the CSV and eyeball the data")
    print(f"  2. Check the token estimate above")
    print(f"     - Under 50K tokens  → can do local API easily")
    print(f"     - 50K-500K tokens   → batch locally (5-10 rows per call)")
    print(f"     - 500K+ tokens      → Snowflake Cortex recommended")


if __name__ == "__main__":
    main()